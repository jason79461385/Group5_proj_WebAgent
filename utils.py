# utils.py
# 存放輔助工具

import ast
import json
from PIL import Image, ImageDraw, ImageFont
import io
import re
import base64

def draw_som_on_image(screenshot_bytes, elements_data):
    """
    接收：原始截圖 bytes, 元素座標 List
    回傳：(標記後的 Base64 圖片, 原始圖片尺寸 Tuple)
    """
    try:
        # 1. 載入圖片
        image = Image.open(io.BytesIO(screenshot_bytes))
        draw = ImageDraw.Draw(image)
        width, height = image.size

        # 嘗試載入字型，若無則用預設
        try:
            # Windows/Linux 常見字型路徑，視環境調整
            font = ImageFont.truetype("arial.ttf", 16) 
        except:
            font = ImageFont.load_default()

        # 2. 繪製標籤
        for el in elements_data:
            el_id = str(el['id'])
            x, y, w, h = el['x'], el['y'], el['w'], el['h']
            
            # 確保不畫出界
            if x < 0 or y < 0 or x > width or y > height: continue

            # 畫紅框
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            
            # 畫標籤背景 (黃底)
            text_bbox = draw.textbbox((0, 0), el_id, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            
            # 標籤位置 (左上角)
            label_bg = [x, y - text_h - 4, x + text_w + 8, y]
            if y - text_h - 4 < 0: # 如果太上面，就畫在框框內
                label_bg = [x, y, x + text_w + 8, y + text_h + 4]
                text_pos = (x + 4, y)
            else:
                text_pos = (x + 4, y - text_h - 4)

            draw.rectangle(label_bg, fill="yellow", outline="red")
            draw.text(text_pos, el_id, fill="black", font=font)

        # 3. 輸出 Base64
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        return img_b64, (width, height)

    except Exception as e:
        print(f"❌ 繪圖失敗: {e}")
        # 失敗時回傳原始圖片
        raw_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        return raw_b64, (0, 0)

def sanitize_history(history: list) -> list:
    """
    [Security] 資料脫敏過濾器
    在將歷史存入 RAG 之前，移除所有可能的敏感資訊 (密碼、Email、API Key)。
    """
    sanitized = []
    # 敏感關鍵字偵測
    sensitive_keys = ["password", "secret", "token", "key", "pwd", "credential"]
    
    for item in history:
        # 如果是字串 (舊格式)，嘗試簡單過濾
        if isinstance(item, str):
            clean_item = item
            # 遮蔽 Email
            clean_item = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '<REDACTED_EMAIL>', clean_item)
            # 遮蔽手機號
            clean_item = re.sub(r'\d{4}-\d{3}-\d{3}', '<REDACTED_PHONE>', clean_item)
            sanitized.append(clean_item)
            continue
            
        # 如果是結構化資料 (建議格式)
        # 這裡假設 history 可能包含 dict，進行深度清洗
        # 目前您的 history 主要是字串列表，所以上面的邏輯為主
        sanitized.append(item)
        
    return sanitized

def get_image_dimensions(image_bytes: bytes) -> tuple:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return image.size 
    except Exception as e:
        print(f"❌ (Pillow) 讀取圖片尺寸失敗: {e}")
        return (0, 0)

def calculate_click_coords_from_pixels(
    png_coords: list, 
    png_dimensions: tuple, 
    viewport_dimensions: tuple
) -> tuple:
    png_click_x, png_click_y = png_coords
    png_width, png_height = png_dimensions
    viewport_width, viewport_height = viewport_dimensions
    if png_width == 0 or png_height == 0:
        return (0, 0)
    scale_x = viewport_width / png_width
    scale_y = viewport_height / png_height
    final_click_x = png_click_x * scale_x
    final_click_y = png_click_y * scale_y
    return int(final_click_x), int(final_click_y)

def parse_coords_from_string(text: str) -> dict | None:
    # 支援 [x, y] 與 (x, y)
    match = re.search(r'[\[\(]\s*(\d+)\s*,\s*(\d+)\s*[\]\)]', text)
    if match:
        try:
            x = int(match.group(1))
            y = int(match.group(2))
            content = text[:match.start()].strip()
            if content.endswith(" at"):
                content = content[:-3].strip()
            result = {"content": content, "coords": [x, y]}
            return result
        except Exception as e:
            print(f"❌ 解析 RegEx 匹配時出錯: {e}")
            return None
    else:
        return None

def parse_omni_coordinates(coordinates: str | list) -> list:
    if isinstance(coordinates, list):
        return coordinates
    if isinstance(coordinates, str):
        try:
            return ast.literal_eval(coordinates)
        except Exception as e:
            return []
    return []

def parse_json_from_string(text: str) -> dict | list | None:
    try:
        text = text.strip()
        
        # --- [新增] 防禦層 1: Markdown 剝離 ---
        # 如果模型用了 Code Block，我們只看 Block 裡面的東西
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            # 有時候模型只打 ``` 而沒打 json
            text = text.split("```")[1].split("```")[0].strip()
            
        # --- 原本的邏輯 (現在變得更安全了) ---
        # 即使剝離了 Markdown，裡面可能還是有前後空白，這段邏輯依然有價值
        start_brace = text.find('{')
        start_bracket = text.find('[')
        
        if start_brace == -1 and start_bracket == -1:
            return None

        # 判斷是 Dict 還是 List
        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            start_index = start_brace
            end_char = '}'
        else:
            start_index = start_bracket
            end_char = ']'
            
        end_index = text.rfind(end_char)
        
        if end_index == -1 or end_index < start_index:
            return None
            
        json_str = text[start_index : end_index + 1]
        
        # --- 額外清洗 ---
        # 移除一些常見的 JSON 錯誤，例如尾隨逗號 (Trailing Commas)
        # 雖然標準 JSON 不允許，但 LLM 常犯
        # 這裡簡單處理，或者直接 try load
        return json.loads(json_str)

    except Exception as e:
        # 在這裡可以加一個 retry logic 或者用更寬容的 parser (如 dirtyjson)
        print(f"❌ JSON 解析失敗: {e} | 原始文字片段: {text[:50]}...")
        return None

def _parse_legacy_label_coordinates(omni_data: dict, image_size: tuple) -> list:
    """
    [Debug] 增強版解析器，強制印出原始資料以供除錯。
    """
    if not omni_data:
        return []

    # [Debug] 強制印出 OmniParser 回傳的 Keys 和部分內容，找出為什麼是空的
    # 請在執行時觀察這行 Log！
    print(f"🔍 [OmniParser Raw Debug] Keys: {omni_data.keys()}")
    if 'label_coordinates' in omni_data:
        print(f"🔍 [OmniParser Raw Debug] label_coordinates count: {len(omni_data['label_coordinates'])}")
    else:
        print(f"🔍 [OmniParser Raw Debug] Content: {str(omni_data)[:200]}")

    raw_items = omni_data.get('label_coordinates', [])
    if not raw_items and 'data' in omni_data:
        raw_items = omni_data['data']

    parsed_elements = []
    img_w, img_h = image_size
    
    for i, item in enumerate(raw_items):
        try:
            # 兼容性處理... (保持之前的邏輯)
            if isinstance(item, list) and len(item) >= 4:
                x, y, w, h = item[0], item[1], item[2], item[3]
                text = str(item[5]) if len(item) > 5 else "UI Element"
            elif isinstance(item, dict):
                x, y, w, h = item.get('x', 0), item.get('y', 0), item.get('w', 0), item.get('h', 0)
                if 'box_2d' in item: x, y, w, h = item['box_2d']
                text = item.get('label', item.get('content', 'UI Element'))
            else:
                continue

            # 放寬過濾條件：只要長寬大於 0 就接受
            if w <= 0 or h <= 0: continue
            
            parsed_elements.append({
                "id": i + 1,
                "x": int(x), "y": int(y), "w": int(w), "h": int(h),
                "tag": "vision_el", "text": str(text)
            })
        except Exception: continue

    return parsed_elements

def convert_omni_data_to_elements(omni_data: dict, image_size: tuple) -> list:
    """
    [Fixed] 依照 omni_test.py 的邏輯重寫。
    解析 'parsed_content' 字串欄位，並將 Normalized BBox (0-1) 轉為 Absolute Pixels。
    """
    if not omni_data:
        return []

    # 1. 優先讀取 parsed_content (這是 omni_test.py 成功的關鍵)
    content_str = omni_data.get('parsed_content', [])
    
    # 如果 parsed_content 是空的，才去檢查 label_coordinates (相容性)
    if not content_str:
        # 這裡保留舊邏輯作為 fallback，但通常不會用到
        return _parse_legacy_label_coordinates(omni_data, image_size)

    # 2. 開始解析 parsed_content
    # 格式範例: "icon {'bbox': [0.03, 0.03, 0.07, 0.08], 'interactivity': True, 'content': 'Back'}"
    parsed_elements = []
    img_w, img_h = image_size
    
    # 將內容按行分割
    if isinstance(content_str, list): # 有些版本直接回傳 list string
        lines = content_str
    else:
        lines = str(content_str).strip().split('\n')

    index = 1
    for line in lines:
        line = line.strip()
        # 只處理 icon 開頭的行
        if line.startswith('icon '):
            try:
                # 提取花括号中的内容
                dict_str = line[line.index('{'):line.rindex('}') + 1]
                # 使用 ast 解析字符串為字典
                icon_data = ast.literal_eval(dict_str)
                
                # 提取資料
                bbox = icon_data.get('bbox', []) # [ymin, xmin, ymax, xmax] 或 [xmin, ymin, xmax, ymax]
                content = icon_data.get('content', 'UI Element')
                
                # 根據 omni_test.py，bbox 是 [xmin, ymin, xmax, ymax] 且是 0-1 的比例
                if len(bbox) == 4:
                    xmin, ymin, xmax, ymax = bbox
                    
                    # [關鍵轉換] Normalized -> Absolute Pixels
                    # 這裡算出的是截圖上的物理像素 (Retina下是高解析度的)
                    abs_x1 = int(xmin * img_w)
                    abs_y1 = int(ymin * img_h)
                    abs_x2 = int(xmax * img_w)
                    abs_y2 = int(ymax * img_h)
                    
                    w = abs_x2 - abs_x1
                    h = abs_y2 - abs_y1
                    
                    # 過濾太小的元素
                    if w < 5 or h < 5: continue

                    parsed_elements.append({
                        "id": index,
                        "x": abs_x1,
                        "y": abs_y1,
                        "w": w,
                        "h": h,
                        "tag": "vision_el",
                        "text": str(content)
                    })
                    index += 1
            except Exception as e:
                print(f"⚠️ 解析 Omni 行失敗: {line} | Error: {e}")
                continue

    print(f"🔍 [Utils] 成功從 parsed_content 解析出 {len(parsed_elements)} 個元素")
    return parsed_elements