# browser_controller.py
# [Refactor] 真實滑鼠操作 (ActionChains) + 單一視窗策略 + DOM 驗證

import undetected_chromedriver as uc
import sys
import time
from pathlib import Path
import hashlib
import numpy as np
from PIL import Image
import io
import os
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException, MoveTargetOutOfBoundsException
from config import CHROME_PROFILE_NAME
from human_mouse import human_move_to_element


class ActionVerifier:
    """
    [New] 輕量級動作驗證器
    用途：在執行動作 (Click/Type) 前後快照，判斷頁面是否發生預期變化。
    """
    def __init__(self, driver):
        self.driver = driver
        self.start_url = driver.current_url
        self.start_dom_hash = self._get_dom_hash()
        self.start_time = time.time()

    def _get_dom_hash(self):
        """ 計算輕量級 DOM 指紋 (只取 Body 文字的前 5000 字) """
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            # 移除空白以減少雜訊
            clean_text = "".join(body_text.split())[:5000]
            return hashlib.md5(clean_text.encode('utf-8')).hexdigest()
        except:
            return "error"

    def verify_action(self, timeout=3.0, check_interval=0.5):
        """
        檢查動作是否生效
        回傳: (success: bool, reason: str)
        """
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            try:
                current_url = self.driver.current_url
                current_hash = self._get_dom_hash()
                
                # 1. 檢查 URL 是否變了 (最強指標：跳轉)
                if current_url != self.start_url:
                    return True, "URL Changed"
                
                # 2. 檢查 DOM 是否變了 (次強指標：內容刷新/選單展開)
                if current_hash != self.start_dom_hash:
                    return True, "DOM Updated"
                    
                time.sleep(check_interval)
            except:
                pass # 忽略瀏覽器在切換過程中的短暫錯誤
            
        return False, "No Change Detected"
    

def initialize_agent() -> uc.Chrome | None:    
    print("[Browser] 啟動中 (含 CDP 反偵測注入)...")
    options = uc.ChromeOptions()
    USER_DATA_DIR = Path.home() / CHROME_PROFILE_NAME
    options.add_argument(f"--user-data-dir={str(USER_DATA_DIR)}")
    options.add_argument("--window-size=1920,1080")
    
    # [Tips] 增加這行可以減少自動化特徵，但有時會影響擴充功能
    # options.add_argument("--disable-blink-features=AutomationControlled")

    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.geolocation": 1,
        "profile.default_content_setting_values.media_stream_mic": 2,
        "profile.default_content_setting_values.media_stream_camera": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False 
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-infobars")
    
    try:
        driver = uc.Chrome(options=options)
        
        # ================= [New] CDP Stealth Injection =================
        # 這是 SOTA 等級的反偵測技術：在頁面載入前注入 JS 覆蓋指紋
        
        stealth_js = """
            // 1. 覆蓋 navigator.webdriver (雖然 UC 有修，但雙重保險)
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // 2. 偽造 Chrome 插件列表 (Headless/Automation 通常是空的)
            // 讓它看起來像有安裝 PDF Viewer 等預設插件
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5] 
            });

            // 3. 偽造 WebGL 供應商 (關鍵！防止被識破是 VM 或 Headless)
            // 如果你是用 A6000，網站可能會看到 Nvidia，這很好。
            // 但如果是在 Docker 內部，可能會變成 SwiftShader，這就需要偽裝。
            try {
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    // UNMASKED_VENDOR_WEBGL
                    if (parameter === 37445) return 'Intel Inc.';
                    // UNMASKED_RENDERER_WEBGL
                    if (parameter === 37446) return 'Intel(R) Iris(R) Xe Graphics';
                    return getParameter(parameter);
                };
            } catch (err) {}

            // 4. 偽造 window.chrome (有些舊檢測會看這個)
            if (!window.chrome) {
                window.chrome = {
                    runtime: {}
                };
            }
            
            // 5. 偽造 Permissions API (讓通知檢測看起來更自然)
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """
        
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": stealth_js
        })
        # ===============================================================

        driver.set_page_load_timeout(30)
        time.sleep(1) # 給一點時間讓 CDP 生效
        
        # 先去一個檢測網站測試 (可選，或直接去 Google)
        driver.get("https://www.google.com")
        
        return driver
    except Exception as e:
        print(f"❌ 啟動錯誤: {e}")
        if "Expecting ',' delimiter" in str(e) or "JSON" in str(e):
            print("🧹 偵測到設定檔損壞，正在清除並重試...")
            try:
                if os.path.exists(str(USER_DATA_DIR)):
                    shutil.rmtree(str(USER_DATA_DIR), ignore_errors=True)
                
                # 再次嘗試啟動
                driver = uc.Chrome(options=options)
                # ... (記得補上 CDP 注入代碼) ...
                return driver
            except Exception as retry_e:
                print(f"❌ 重試失敗: {retry_e}")
        return None


def get_interactive_elements_coordinates(driver):
    """
    [Updated] V7 - Hybrid Safe Mode
    Plan A (WebVoyager): 精確 Hit Testing，防止點擊遮擋。
    Plan B (Fallback): 如果 Plan A 失敗 (回傳 0 個)，切換到寬鬆模式，只檢查可見性。
    這保證了 Agent 絕對不會因為判定太嚴格而「瞎掉」。
    """
    js = """
    (function() {
        // --- Plan A: WebVoyager (Strict) ---
        function runPlanA() {
            try {
                const results = [];
                
                function isInteractive(element, style) {
                    const tag = element.tagName.toLowerCase();
                    if (['a', 'button', 'input', 'textarea', 'select', 'video', 'iframe'].includes(tag)) return true;
                    if (element.getAttribute('role') === 'button' || element.getAttribute('type') === 'button') return true;
                    if (element.onclick != null || style.cursor === 'pointer') return true;
                    if (element.id === 'video-title' || tag === 'ytd-thumbnail') return true;
                    return false;
                }

                function getVisibleRect(element) {
                    const rect = element.getBoundingClientRect();
                    if (rect.width < 5 || rect.height < 5) return null;
                    
                    const winH = window.innerHeight || document.documentElement.clientHeight;
                    const winW = window.innerWidth || document.documentElement.clientWidth;
                    if (rect.top >= winH || rect.bottom <= 0 || rect.left >= winW || rect.right <= 0) return null;

                    const style = window.getComputedStyle(element);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return null;
                    
                    // Strict Hit Testing
                    const centerX = rect.left + rect.width / 2;
                    const centerY = rect.top + rect.height / 2;
                    const x = (centerX > 0 && centerX < winW) ? centerX : (rect.left + 5);
                    const y = (centerY > 0 && centerY < winH) ? centerY : (rect.top + 5);

                    const topEl = document.elementFromPoint(x, y);
                    if (!topEl) return null;
                    if (topEl === element || element.contains(topEl) || topEl.contains(element)) return rect;
                    return null;
                }

                function traverse(root) {
                    const elements = root.querySelectorAll('*');
                    elements.forEach(el => {
                        if (el.shadowRoot) traverse(el.shadowRoot);
                        try {
                            const style = window.getComputedStyle(el);
                            const rect = getVisibleRect(el);
                            if (rect && isInteractive(el, style)) {
                                let text = el.innerText || el.value || el.getAttribute('aria-label') || "";
                                text = text.slice(0, 100).replace(/[\\n\\t]/g, " ").trim();
                                if (text.length > 0 || ['input', 'img', 'button', 'ytd-thumbnail'].includes(el.tagName.toLowerCase())) {
                                    results.push({
                                        "x": rect.x, "y": rect.y, "w": rect.width, "h": rect.height,
                                        "tag": el.tagName.toLowerCase(), "text": text
                                    });
                                }
                            }
                        } catch(e) {}
                    });
                }
                
                const root = document.querySelector('ytd-app') || document.body;
                traverse(root);
                return results;
            } catch (e) { return []; }
        }

        // --- Plan B: Loose Mode (Fallback) ---
        function runPlanB() {
            // 放棄 elementFromPoint，只檢查 getBoundingClientRect
            // 這是為了防止 "明明看得到卻點不到" 的 JS 判定誤差
            const results = [];
            const items = document.querySelectorAll('a, button, input, [role="button"], [onclick], ytd-thumbnail, #video-title');
            
            items.forEach(el => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (rect.width > 5 && rect.height > 5 && style.display !== 'none' && style.visibility !== 'hidden') {
                    let text = el.innerText || el.value || "";
                    results.push({
                        "x": rect.x, "y": rect.y, "w": rect.width, "h": rect.height,
                        "tag": el.tagName.toLowerCase(), "text": text.slice(0, 50).trim()
                    });
                }
            });
            return results;
        }

        // --- Execution Strategy ---
        let finalResults = runPlanA();
        
        // 如果 Plan A 失敗 (例如 0 個元素)，啟用 Plan B
        if (!finalResults || finalResults.length === 0) {
            finalResults = runPlanB();
            finalResults.push({"type": "PLAN_B"}); // 標記用
        }
        
        return finalResults;
    })();
    """
    
    try:
        raw_elements = driver.execute_script(js)
        
        if not raw_elements:
            return []

        # 簡單去重 (Python 端)
        final_elements = []
        seen_coords = []
        is_plan_b = False
        
        for el in raw_elements:
            if el.get("type") == "PLAN_B":
                is_plan_b = True
                continue
                
            # 去重邏輯
            is_dup = False
            for seen in seen_coords:
                if abs(el['x'] - seen[0]) < 10 and abs(el['y'] - seen[1]) < 10:
                    is_dup = True; break
            if not is_dup:
                final_elements.append(el)
                seen_coords.append((el['x'], el['y']))

        # 賦予 ID
        for i, el in enumerate(final_elements):
            el['id'] = i + 1
            
        if is_plan_b:
            print(f"⚠️ [Browser] Plan A 失敗，已切換至 Plan B (寬鬆模式)。掃描到 {len(final_elements)} 個目標。")
        else:
            print(f"👁️ [Browser] SoM 掃描完成: {len(final_elements)} 個目標")
            
        return final_elements

    except Exception as e:
        print(f"❌ SoM 提取失敗: {e}")
        return []
    
def smart_wait_for_change(driver: webdriver.Chrome, timeout=5.0):
    """
    [New Logic] 等待頁面發生變化 (用於動作執行後)
    """
    start_url = driver.current_url
    try:
        start_dom_len = len(driver.page_source)
    except:
        start_dom_len = 0
        
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # 1. 檢查 URL 是否變了 (最強指標)
        if driver.current_url != start_url:
            print("🚀 [Browser] URL changed, page loaded.")
            # URL 變了之後，通常需要再等一下 Stability，這裡簡單 sleep 即可
            time.sleep(2.0) 
            return True
            
        # 2. 檢查 DOM 長度變化 (針對 AJAX 搜尋結果)
        try:
            current_dom_len = len(driver.page_source)
            if abs(current_dom_len - start_dom_len) > 500: # 內容變動超過 500 chars
                print("⚡ [Browser] DOM content changed significantly.")
                time.sleep(1.0) # 等待渲染完成
                return True
        except: pass
            
        time.sleep(0.5)
    
    print("⏳ [Browser] No significant change detected (Timeout).")
    return False

def wait_for_page_stability(driver: webdriver.Chrome, timeout=10, check_interval=0.5):
    """
    [Old Logic] 等待頁面變動停止 (用於截圖前)
    """
    print("⏳ [Browser] Waiting for stability...")
    
    def get_dom_hash(d):
        try:
            body = d.find_element(By.TAG_NAME, "body").text
            return hashlib.md5(body[:5000].encode('utf-8')).hexdigest()
        except:
            return "error"

    end_time = time.time() + timeout
    last_hash = get_dom_hash(driver)
    stable_count = 0
    
    while time.time() < end_time:
        time.sleep(check_interval)
        current_hash = get_dom_hash(driver)
        
        if current_hash == last_hash:
            stable_count += 1
        else:
            stable_count = 0
            last_hash = current_hash
            
        if stable_count >= 2: # 連續兩次一樣算穩定
            return True
            
    return True # 超時也當作穩定，避免卡死

def _calculate_visual_diff(img_bytes_1, img_bytes_2):
    """
    計算兩張圖片的差異百分比 (0.0 ~ 100.0)
    使用 Numpy 向量化運算，速度極快 (約 0.02s)
    """
    try:
        # 將 bytes 轉為 PIL Image
        img1 = Image.open(io.BytesIO(img_bytes_1)).convert("RGB")
        img2 = Image.open(io.BytesIO(img_bytes_2)).convert("RGB")
        
        # 確保尺寸一致 (Retina 螢幕有時候會有微小誤差)
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)
            
        # 轉為 Numpy Array
        arr1 = np.array(img1, dtype=np.int16) # 使用 int16 避免相減溢出
        arr2 = np.array(img2, dtype=np.int16)
        
        # 計算絕對差值
        diff = np.abs(arr1 - arr2)
        
        # 設定一個閾值，過濾掉 JPEG 壓縮雜訊 (例如 RGB 差異 < 15 視為相同)
        # 產生一個 Boolean Mask
        mask = np.any(diff > 15, axis=-1)
        
        # 計算變動像素的比例
        change_ratio = np.sum(mask) / mask.size * 100
        
        return change_ratio
    except Exception as e:
        print(f"⚠️ 視覺比對失敗: {e}")
        return 100.0 # 失敗時預設視為有變動，避免誤判死循環

def _inject_visual_cursor(driver: webdriver.Chrome):
    js = """
    if (!document.getElementById('agent-cursor')) {
        let c = document.createElement('div');
        c.id = 'agent-cursor';
        c.style.position = 'absolute';
        c.style.width = '20px'; c.style.height = '20px';
        c.style.background = 'rgba(255, 0, 0, 0.7)';
        c.style.borderRadius = '50%'; c.style.zIndex = '999999';
        c.style.pointerEvents = 'none'; c.style.transition = 'all 0.3s ease-out';
        document.body.appendChild(c);
    }
    """
    driver.execute_script(js)

def _move_visual_cursor(driver: webdriver.Chrome, x: int, y: int):
    _inject_visual_cursor(driver)
    driver.execute_script(f"let c=document.getElementById('agent-cursor');if(c){{c.style.left='{x-10}px';c.style.top='{y-10}px';}}")
    time.sleep(0.3)

def batch_get_element_details(driver, coordinates_list):
    """
    輸入：一個包含 {'x', 'y'} 的列表 (邏輯像素座標)
    輸出：對應 DOM 元素的詳細資訊 (tagName, text, aria-label, href)
    """
    js_script = """
    const coords = arguments[0];
    const results = [];
    
    // Helper: 安全讀取屬性
    const getAttr = (el, name) => {
        try {
            const val = el.getAttribute(name);
            return val ? val.trim() : "";
        } catch (e) { return ""; }
    };

    for (let i = 0; i < coords.length; i++) {
        const pt = coords[i];
        let el = document.elementFromPoint(pt.x, pt.y);
        
        if (!el) {
            results.push({ text: "", tag: "unknown", attr: "", id: "", class: "" });
            continue;
        }
        
        const interactive = el.closest('a, button, input, select, textarea, [role="button"], [onclick]');
        if (interactive) el = interactive;
        
        // --- 屬性收集 (含 ARIA 狀態) ---
        let attrs = [];
        
        const href = getAttr(el, 'href');
        if (href && href !== '#' && !href.startsWith('javascript:')) attrs.push(`href: ${href}`);
        
        // [New] 狀態感知：這對 Dropdown 非常重要
        const expanded = getAttr(el, 'aria-expanded');
        if (expanded) attrs.push(`expanded: ${expanded}`); // 'true' or 'false'
        
        const dataState = getAttr(el, 'data-state'); 
        if (dataState) attrs.push(`state: ${dataState}`); // 'open' or 'closed' (常見於 Shadcn UI)
        
        const role = getAttr(el, 'role');
        if (role) attrs.push(`role: ${role}`);
        
        const label = getAttr(el, 'aria-label');
        if (label) attrs.push(`label: ${label}`);

        // 文字提取
        let text = el.innerText || el.textContent || "";
        text = text.trim();
        if (text.length === 0) {
            text = getAttr(el, 'value') || getAttr(el, 'alt') || label || "";
        }
        
        let className = "";
        try { className = (typeof el.className === 'string') ? el.className : ""; } catch(e){}

        results.push({
            text: text.slice(0, 100).replace(/[\\n\\t]/g, " "),
            tag: (el.tagName || "unknown").toLowerCase(),
            class: className.slice(0, 50),
            id: el.id || "",
            attr: attrs.join(" | ")
        });
    }
    return results;
    """
    
    try:
        return driver.execute_script(js_script, coordinates_list)
    except Exception as e:
        print(f"❌ Visual-DOM Alignment JS 執行失敗: {e}")
        return None
 
def force_remove_element_by_coords(driver, x, y):
    print(f"☢️ [Browser] 啟動 DOM 移除程序，目標座標: ({x}, {y})")
    
    js_script = """
    const x = arguments[0];
    const y = arguments[1];
    const el = document.elementFromPoint(x, y);
    
    if (!el) return "No element found";
    
    // 1. 嘗試找到這元素的「容器」(通常是 fixed 或 absolute 定位的彈窗)
    // 我們往上找 5 層，尋找是否有像彈窗特徵的父元素
    let targetToRemove = el;
    let current = el;
    
    for (let i = 0; i < 5; i++) {
        if (!current || current.tagName === 'BODY' || current.tagName === 'HTML') break;
        
        const style = window.getComputedStyle(current);
        // 如果父層是浮動視窗 (Fixed/Absolute) 且 z-index 很高，那它就是彈窗本體
        if ((style.position === 'fixed' || style.position === 'absolute') && style.zIndex > 10) {
            targetToRemove = current;
            break;
        }
        current = current.parentElement;
    }
    
    // 2. 執行刪除
    console.log("Removing element:", targetToRemove);
    targetToRemove.remove();
    
    // 3. 額外清理：有時候刪了彈窗，背景還是灰色的鎖定狀態 (overflow: hidden)
    document.body.style.overflow = 'auto'; 
    document.documentElement.style.overflow = 'auto';
    
    return "Removed " + targetToRemove.tagName;
    """
    
    try:
        result = driver.execute_script(js_script, x, y)
        print(f"✅ 成功移除元素: {result}")
        return True
    except Exception as e:
        print(f"❌ DOM 移除失敗: {e}")
        return False
     
# --- 真實操作 (ActionChains) ---

def perform_scroll(driver: webdriver.Chrome, direction: str = "down", amount: int = 400):
    try:
        # 紀錄捲動前的位置
        start_y = driver.execute_script("return window.scrollY;")
        total_height = driver.execute_script("return document.body.scrollHeight;")
        viewport_height = driver.execute_script("return window.innerHeight;")
        # 執行捲動
        # 檢查是否已經到底
        if direction == "down" and (start_y + viewport_height) >= total_height:
            print("🛑 [Scroll] 已達頁面底部，無法再向下。")
            return False

        # 2. 執行平滑捲動 (Smooth Scroll - 也是擬人化的一環)
        driver.execute_script(f"window.scrollBy({{top: {amount}, behavior: 'smooth'}});")
        time.sleep(0.8) # 等待捲動動畫與內容加載
        # 紀錄捲動後的位置
        end_y = driver.execute_script("return window.scrollY;")
        
        if start_y == end_y:
            print("⚠️ [Browser] 捲動無效 (已達底部或被鎖定)")
            return False # 告訴 Agent 捲不動了
            
        return True
    except Exception as e:
        print(f"❌ 捲動失敗: {e}")
        return False

def click_element_by_text(driver, text):
    """
    [Fallback] 當座標點擊失敗時，嘗試用文字內容直接尋找元素並點擊
    這對 Hugging Face 的 Sort/Filter 按鈕非常有效
    """
    if not text or len(text) < 2: return False
    
    # 清洗文字，避免特殊字符導致 XPath 報錯
    clean_text = text.replace("'", "").replace('"', '').strip()
    print(f"🔄 [Fallback] 嘗試使用文字搜尋點擊: '{clean_text}'")
    
    try:
        # 使用 XPath 尋找包含該文字的可點擊元素
        # 1. 包含匹配 (針對 'Sort: Trending' 這種變動文字)
        xpath_contains = f"//*[contains(text(), '{clean_text}')]"
        
        elements = driver.find_elements(By.XPATH, xpath_contains)
        
        # 過濾出可見且可點擊的元素
        for el in elements:
            if el.is_displayed():
                # 檢查是否為按鈕或連結，或是其子元素
                tag = el.tag_name.lower()
                # 往上找一層看是不是包在 button 裡
                try:
                    parent = el.find_element(By.XPATH, "./..")
                    parent_tag = parent.tag_name.lower()
                except:
                    parent_tag = ""
                
                if tag in ['a', 'button'] or parent_tag in ['a', 'button'] or el.get_attribute('role') == 'button':
                    print(f"✅ [Fallback] 找到文字對應元素 <{tag}>，執行 JS Click")
                    driver.execute_script("arguments[0].click();", el)
                    return True
        return False
    except Exception as e:
        print(f"❌ 文字救援失敗: {e}")
        return False

def perform_mouse_click(driver: webdriver.Chrome, x: int, y: int, expect_change: bool = True, target_text: str = "") -> bool:
    print(f"--- Action: Click at ({x}, {y}) ---")
    _move_visual_cursor(driver, x, y)
    
    try:
        driver.execute_script("""
            var dot = document.createElement('div');
            dot.style.position = 'absolute';
            dot.style.left = arguments[0] + 'px';
            dot.style.top = arguments[1] + 'px';
            dot.style.width = '8px';
            dot.style.height = '8px';
            dot.style.backgroundColor = 'red';
            dot.style.borderRadius = '50%';
            dot.style.zIndex = '999999';
            dot.style.pointerEvents = 'none';
            dot.style.border = '2px solid yellow'; // 增加對比度
            document.body.appendChild(dot);
            setTimeout(() => dot.remove(), 3000); // 3秒後消失
        """, x-4, y-4)
        
        # 儲存除錯截圖
        debug_dir = "logs/debug_clicks"
        if not os.path.exists(debug_dir): os.makedirs(debug_dir)
        timestamp = int(time.time() * 1000)
        driver.save_screenshot(f"{debug_dir}/click_{timestamp}.png")
    except: pass

    # 1. [Optimization] 預先截圖 (用於後續視覺比對)
    png_before = None
    if expect_change:
        try:
            png_before = driver.get_screenshot_as_png()
        except: pass

    try:
        # 2. [Interactive Check] 獲取該座標的元素並檢查
        target_info = driver.execute_script("""
            var el = document.elementFromPoint(arguments[0], arguments[1]);
            if (!el) return null;
            return { element: el, tagName: el.tagName.toLowerCase(), type: el.type };
        """, x, y)
        
        if not target_info:
            print("❌ 該座標無元素")
            return False
            
        target = target_info['element']
        tag_name = target_info['tagName']
        
        print(f"🎯 [Click Check] 原始目標: <{tag_name}> at ({x}, {y})")

        # 3. [Smart Bubble-up] 智慧修正邏輯 (尋找可點擊父層)
        clickable_target = driver.execute_script("""
            let el = arguments[0];
            const interactiveTags = ['a', 'button', 'input', 'textarea', 'select', 'label', 'summary'];
            
            for (let i = 0; i < 5; i++) {
                if (!el) return null;
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role');
                
                if (interactiveTags.includes(tag) || role === 'button' || el.onclick || window.getComputedStyle(el).cursor === 'pointer') {
                    return el;
                }
                el = el.parentElement;
            }
            return null;
        """, target)
        
        # 4. [Precision Decision] 決策：擬人中心點擊 vs JS 強制點擊
        final_element = target 
        use_js_click = False   

        if clickable_target:
            print(f"🔧 [Smart Fix] 修正目標: 從 <{tag_name}> -> <{clickable_target.tag_name}> (使用 ActionChains 點擊中心)")
            final_element = clickable_target
            use_js_click = False 
        else:
            print(f"⚠️ [Precision] 未發現明確互動父層，保留原始目標 <{tag_name}>。啟用 JS Click 以確保座標精準度。")
            use_js_click = True
        # ================= [New] 輸入框豁免機制 (Input Exemption) =================
        # 這是為了防止對 Input 點擊時，Verifier 因為畫面沒變而誤報失敗
        is_input = False
        try:
            # 檢查 final_element 的標籤名稱
            tag = driver.execute_script("return arguments[0].tagName.toLowerCase();", final_element)
            # 如果是 input 或 textarea，視為輸入框
            is_input = tag in ['input', 'textarea']
        except: pass

        if is_input:
            print("⚡ [Browser] Target is INPUT. Skipping verification (Focus click).")
            expect_change = False # 強制關閉驗證，讓後面的邏輯走快速通道
        # ======================================================================
        # 5. [Execution] 執行點擊
        if use_js_click:
            driver.execute_script("arguments[0].click();", final_element)
            print("✅ JS 點擊執行完畢")
        else:
            # --- [Modified] 使用擬人化移動 ---
            # 舊代碼: actions = ActionChains(driver); actions.move_to_element...
            # 新代碼: 使用 human_move_to_element 獲取已設定好軌跡的 actions
            actions = human_move_to_element(driver, final_element)
            # [Fix] 防呆檢查：如果回傳的不是 ActionChains (例如回傳了 True/False)，就重建一個
            if not isinstance(actions, ActionChains):
                print("⚠️ [Bug Fix] human_move_to_element 回傳了非 ActionChains 物件，強制重建。")
                actions = ActionChains(driver).move_to_element(final_element)
            actions.click()
            actions.perform()
            print("✅ 擬人化 ActionChains 點擊執行完畢")

        # ================= [Logic Branch] 驗證分流 =================
        if not expect_change:
            # [Path A] 快速通道 (Fast Path) - 用於輸入框聚焦
            print("⚡ [Browser] Skipped verification (Focus click).")
            time.sleep(0.3) # 稍微等待 Focus 生效
            return True
        
        else:
            # [Path B] 完整驗證通道 (Verification Path)
            
            # 1. 智慧等待 (Smart Wait)
            dom_changed = smart_wait_for_change(driver, timeout=3.0)
            
            # 2. 視覺比對 (Visual Check)
            diff_ratio = 0.0
            png_after = None
            if png_before:
                try:
                    # 只有當 DOM 沒變時，才需要認真看截圖 (節省資源)
                    if not dom_changed:
                        png_after = driver.get_screenshot_as_png()
                        diff_ratio = _calculate_visual_diff(png_before, png_after)
                        print(f"👀 [Verifier] 視覺差異: {diff_ratio:.2f}%")
                except: pass

            # 3. 判定是否失敗：DOM 沒變 且 視覺差異極小 (< 0.5%) 且 不是 JS Click
            if not dom_changed and diff_ratio < 0.5 and not use_js_click:
                print("⚠️ [Verifier] 警告：畫面未發生顯著變化，點擊可能失敗！")
                
                # --- Rescue Layer 1: Force JS Click (原地重試) ---
                print("🔄 [Auto-Retry L1] 啟動原地重試：強制切換為 JS Click...")
                try:
                    driver.execute_script("arguments[0].click();", final_element)
                    
                    # 重試後檢查
                    if smart_wait_for_change(driver, timeout=3.0):
                        print("✅ [Verifier] JS 重試成功 (DOM Changed)。")
                        return True
                    
                    # --- Rescue Layer 2: Text-Based Fallback (文字救援) ---
                    # 如果原地重試失敗，且我們有目標文字，嘗試用文字搜尋點擊
                    if target_text and len(target_text) > 1:
                        print(f"🔄 [Auto-Retry L2] JS 重試無效，啟動文字救援: '{target_text}'...")
                        # 呼叫我們之前定義的 click_element_by_text
                        if click_element_by_text(driver, target_text):
                            if smart_wait_for_change(driver, timeout=5.0):
                                print("✅ [Verifier] 文字救援成功！")
                                return True
                            else:
                                print("⚠️ [Verifier] 文字救援執行了，但畫面仍未變動。")
                        else:
                            print("❌ [Verifier] 文字救援找不到對應元素。")

                    # 最後手段：再看一次截圖，也許重試後畫面變了但 DOM 沒變 (例如 Canvas)
                    if png_after:
                        png_retry = driver.get_screenshot_as_png()
                        diff_retry = _calculate_visual_diff(png_after, png_retry)
                        print(f"👀 [Verifier] L1/L2 重試後視覺差異: {diff_retry:.2f}%")
                        if diff_retry > 0.5:
                            print("✅ [Verifier] 最終確認：畫面已發生視覺變化。")
                            return True

                    print("❌ [Verifier] 所有救援手段無效 (可能是無效按鈕或死連結)。")
                    # 雖然失敗，回傳 True 讓流程繼續，交給 Brain 決定下一步
                    return True 

                except Exception as e:
                    print(f"❌ 重試過程發生錯誤: {e}")
            
            return True
        # ==========================================================

    except Exception as e:
        print(f"⚠️ 點擊發生異常 ({e})")
        # 最後的保險：盲點座標
        try:
            print("🔄 嘗試最終 Fallback: JS 座標強制點擊...")
            driver.execute_script("document.elementFromPoint(arguments[0], arguments[1]).click();", x, y)
            if expect_change:
                smart_wait_for_change(driver)
            return True
        except:
            return False
        
def wait_for_input_stability(driver: webdriver.Chrome, min_wait=1.0, timeout=10.0):
    """
    [New] 等待輸入框相關的 DOM 穩定 (Debounce Wait)
    用途：在打完字後，等待前端 JS 跑完 (例如 Autocomplete 選單渲染完成)，再按 Enter。
    原理：持續監控頁面 DOM 長度，直到它在 min_wait 時間內不再變動。
    """
    print(f"⏳ [Browser] 等待前端反應 (Input Stability Check)...")
    
    start_time = time.time()
    last_dom_len = len(driver.page_source)
    stable_start = time.time()
    
    # 強制最小等待 (給 JS 一點啟動時間)
    time.sleep(min_wait)
    
    while time.time() - start_time < timeout:
        current_dom_len = len(driver.page_source)
        
        # 容許微小的變動 (例如游標閃爍造成的 DOM 變化)，這裡設閾值為 10 chars
        if abs(current_dom_len - last_dom_len) < 10:
            # 如果 DOM 沒變，檢查是否已經穩定夠久了
            if time.time() - stable_start >= 0.8: # 穩定 0.8 秒視為 Ready
                print("⚡ [Browser] 輸入狀態已穩定 (Ready to Submit).")
                return True
        else:
            # DOM 還在變 (可能正在渲染搜尋建議)，重置穩定計時器
            stable_start = time.time()
            last_dom_len = current_dom_len
            
        time.sleep(0.2)
        
    print("⚠️ [Browser] 等待穩定超時 (強制繼續).")
    return True

def perform_type(driver: webdriver.Chrome, x: int, y: int, text: str) -> bool:
    print(f"⌨️ [Browser] 正在座標 ({x}, {y}) 輸入: '{text}'")
    
    # 1. 點擊並聚焦 (傳入 expect_change=False，避免 Verifier 誤報)
    if perform_mouse_click(driver, x, y, expect_change=False):
        time.sleep(0.5) # 等待 focus
        try:
            active_el = driver.switch_to.active_element
            
            # --- [Focus Correction] 焦點校正機制 ---
            tag_name = active_el.tag_name.lower()
            if tag_name in ['body', 'button', 'div', 'span']:
                print(f"⚠️ [Type Warning] 當前焦點是 <{tag_name}>，可能點偏了。嘗試尋找附近的 Input...")
                corrected_el = driver.execute_script("""
                    var x = arguments[0];
                    var y = arguments[1];
                    var el = document.elementFromPoint(x, y);
                    if (el) {
                        var input = el.closest('input, textarea');
                        if (input) return input;
                        var innerInput = el.querySelector('input, textarea');
                        if (innerInput) return innerInput;
                    }
                    return null;
                """, x, y)
                
                if corrected_el:
                    print(f"🔧 [Smart Fix] 找到正確的輸入框 <{corrected_el.tag_name}>，切換焦點！")
                    active_el = corrected_el
                    driver.execute_script("arguments[0].focus();", active_el)
                    time.sleep(0.2)
            # --------------------------------------------

            actions = ActionChains(driver)
            modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
            
            # 2. 清除舊內容
            actions.key_down(modifier_key).send_keys('a').key_up(modifier_key)
            actions.pause(0.1)
            actions.send_keys(Keys.BACK_SPACE)
            actions.pause(0.1)
            
            # 3. 輸入文字
            actions.send_keys(text)
            actions.pause(0.5)
            actions.perform()
            
            # --- [Verification & Rescue] 雙重確認與 JS 救援 ---
            
            current_value = active_el.get_attribute('value')
            if not current_value:
                current_value = active_el.text

            if not current_value or text not in current_value:
                display_val = str(current_value)
                if len(display_val) > 50:
                    display_val = display_val[:50] + "..."
                display_val = display_val.replace('\n', ' ')
                print(f"⚠️ [Type Warning] ActionChains 輸入不完整 (預期: {text}, 實際: {display_val})")
                print("🔄 啟動 Tier 2: 安全版 JS 強制注入...")
                
                # [Anti-Vandalism] 防止塗改按鈕文字的 JS
                safe_js_injector = """
                let el = arguments[0];
                let val = arguments[1];
                try {
                    let tagName = el.tagName.toUpperCase();
                    if (tagName === 'INPUT' || tagName === 'TEXTAREA') {
                        let descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
                        if (descriptor && descriptor.set) {
                            descriptor.set.call(el, val);
                        } else {
                            el.value = val;
                        }
                    } 
                    else if (el.isContentEditable) {
                        el.innerText = val;
                    }
                    else {
                        return "error: Target is <" + tagName + ">, not an input field.";
                    }
                    let events = ['input', 'change', 'blur', 'keydown', 'keyup'];
                    for (let i = 0; i < events.length; i++) {
                        el.dispatchEvent(new Event(events[i], { bubbles: true }));
                    }
                    return "success";
                } catch (err) {
                    return "error: " + err.message;
                }
                """
                result = driver.execute_script(safe_js_injector, active_el, text)
                
                if result and "error" in result:
                    print(f"❌ JS 注入拒絕執行: {result}")
                    return False
                else:
                    print(f"✅ JS 注入執行完畢")
            else:
                print(f"✅ 輸入驗證成功: '{current_value}'")

            # --- [Critical Upgrade] 動態輸入穩定等待 (取代舊的 Debounce Wait) ---
            # 這裡會自動適應 Hugging Face 或其他網站的反應速度
            wait_for_input_stability(driver, min_wait=1.0)
            
            # 4. 發送 Enter
            print("🚀 [Auto-Submit] 發送 Enter 鍵...")
            actions.send_keys(Keys.ENTER)
            actions.perform()
            
            # 5. 等待結果跳轉 (Smart Wait)
            smart_wait_for_change(driver, timeout=8.0)
            
            return True

        except Exception as e:
            print(f"❌ 輸入過程發生錯誤: {e}")
            return False
            
    return False

def perform_keyboard_action(driver: webdriver.Chrome, key_str: str) -> tuple[bool, str]:
    """ 處理按鍵與組合鍵 """
    try:
        actions = ActionChains(driver)
        key_input = str(key_str).lower()
        
        # 簡單映射
        key_map = {
            "enter": Keys.ENTER, "return": Keys.ENTER, "esc": Keys.ESCAPE,
            "tab": Keys.TAB, "backspace": Keys.BACK_SPACE
        }
        
        if key_input in key_map:
            actions.send_keys(key_map[key_input]).perform()
        else:
            actions.send_keys(key_str).perform()
        return True, f"按鍵 {key_str} 完成"
    except Exception as e:
        return False, str(e)

# --- 視窗策略 ---

def handle_window_policy(driver: webdriver.Chrome):
    """
    [Critical Fix] 強制視窗切換邏輯
    確保 driver 永遠指向最新的視窗，並正確關閉舊視窗。
    """
    try:
        all_handles = driver.window_handles
        current_handle = driver.current_window_handle
        
        # 如果只有一個視窗，無需切換
        if len(all_handles) == 1:
            return

        print(f"🔀 偵測到多分頁 ({len(all_handles)} 個)，執行單一視窗策略...")
        
        # 策略：保留最後一個 (最新的) 視窗，關閉其他所有
        latest_handle = all_handles[-1]
        
        for handle in all_handles:
            if handle != latest_handle:
                driver.switch_to.window(handle)
                driver.close()
        
        # 最後切換到最新視窗
        driver.switch_to.window(latest_handle)
        print(f"✅ 已切換至新分頁: {driver.title}")
        
    except Exception as e:
        print(f"⚠️ 視窗切換發生錯誤 (可能視窗已關閉): {e}")
        # 救命措施：嘗試切換到最後一個活著的視窗
        try:
            driver.switch_to.window(driver.window_handles[-1])
        except:
            pass

def cleanup_tabs(driver: webdriver.Chrome):
    """ (任務結束) 只保留當前分頁，關閉其他所有 """
    try:
        current = driver.current_window_handle
        handles = driver.window_handles
        for h in handles:
            if h != current:
                driver.switch_to.window(h)
                driver.close()
        driver.switch_to.window(current)
        print("🧹 已清理多餘分頁，只保留焦點視窗。")
    except Exception as e:
        print(f"⚠️ 清理分頁失敗: {e}")

# --- 輔助 ---
def check_page_content_match(driver: webdriver.Chrome, keywords: str) -> bool:
    """
    增強版 DOM 驗證：
    1. 檢查標題 (Title)
    2. 檢查 H1
    3. 檢查全文 (Body Text) - 解決 Handle 與 Display Name 不一致的問題
    """
    try:
        if not keywords: return False
        keywords = keywords.lower()
        
        # 1. 檢查標題
        if keywords in driver.title.lower(): 
            print(f"✅ [DOM] 標題命中: {driver.title}")
            return True
            
        # 2. 檢查 H1
        for h1 in driver.find_elements(By.TAG_NAME, "h1"):
            if keywords in h1.text.lower(): 
                print(f"✅ [DOM] H1 命中: {h1.text}")
                return True
        
        # 3. [新增] 檢查內文 (解決 'Roger9527' 出現在 ID 而非標題的情況)
        # 為了效能，只取前 5000 字或是特定區塊，但在現代電腦上取 body.text 通常很快
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            # 簡單優化：如果網頁太大，只檢查前 1000 字
            if keywords in body_text[:1000]:
                print(f"✅ [DOM] 頁面內文命中關鍵字 ({keywords})")
                return True
        except:
            pass

        return False
    except: return False

def get_page_state(driver: webdriver.Chrome) -> dict:
    try: return {"url": driver.current_url, "title": driver.title}
    except: return {"url": "unknown", "title": "unknown"}

def wait_for_page_load(driver: webdriver.Chrome):
    try: WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete"); time.sleep(0.5)
    except: pass

def wait_for_url_change(driver: webdriver.Chrome, old_url: str):
    try: WebDriverWait(driver, 10).until(lambda d: d.current_url != old_url)
    except: pass

def perform_goto_url(driver: webdriver.Chrome, url: str) -> bool:
    print(f"🚀 [Smart Jump] Agent 決定直接跳轉至: {url}")
    try:
        driver.get(url)
        # 跳轉後通常需要等待載入
        wait_for_page_load(driver)
        return True
    except Exception as e:
        print(f"❌ 跳轉失敗: {e}")
        return False
    
def click_element_by_text(driver: webdriver.Chrome, text: str) -> bool:
    """
    [通用備案] DOM 文字點擊：搜尋包含特定文字的可見元素並點擊。
    解決視覺模型看不準浮動選單文字的問題。
    """
    print(f"--- Fallback: Attempting to click by text '{text}' ---")
    try:
        # 使用 XPath 尋找包含文字的元素 (不區分大小寫處理比較複雜，這裡先做簡易版)
        # 尋找所有包含該文字的元素
        xpath = f"//*[contains(text(), '{text}')] | //*[contains(@aria-label, '{text}')] | //*[contains(@title, '{text}')]"
        elements = driver.find_elements(By.XPATH, xpath)
        
        target_element = None
        
        # 過濾：只找「顯示中 (Displayed)」且「可點擊」的元素
        for el in elements:
            if el.is_displayed():
                # 這裡也可以復用之前的 "Smart Bubble-up" 邏輯找父層
                target_element = el
                break
        
        if not target_element:
            print(f"❌ DOM 中找不到可見的文字: {text}")
            return False

        # 執行點擊
        actions = ActionChains(driver)
        actions.move_to_element(target_element).pause(0.2).click().perform()
        print(f"✅ DOM 文字點擊成功: {text}")
        return True

    except Exception as e:
        print(f"❌ DOM 文字點擊失敗: {e}")
        return False