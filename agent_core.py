# agent_core.py
# [Updated] V20 - SoM (Set-of-Marks) Architecture with Agentic RAG

import time
import base64
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import hashlib
import html2text
import api_clients
import utils
import browser_controller
import planner_client
import io              
import json
from PIL import Image  
from memory_manager import MemoryManager

class AgentCore:
    def __init__(self, driver, logger = None):
        self.driver = driver
        self.history = []          
        self.max_history_len = 10  
        self.user_goal = ""
        self.is_paused = False     
        self.logger = logger
        self.current_plan = "" #儲存當前計畫
        self.scratchpad = {} # [New] 短期記憶筆記本 (Key-Value)
        # 狀態追蹤
        self.last_page_hash = ""
        self.same_state_action_count = 0
        self.cached_elements_map = None
        self.cached_img_size = None
        try:
            self.memory_manager = MemoryManager()
            print("✅ [Core] RAG 記憶模組連線成功")
        except Exception:
            self.memory_manager = None
        self.rag_data = None

    def _get_page_hash(self):
        """計算當前頁面的狀態指紋 (URL + DOM 前 1000 字)"""
        try:
            dom_sample = self.driver.find_element("tag name", "body").text[:1000]
            raw_data = f"{self.driver.current_url}-{dom_sample}"
            return hashlib.md5(raw_data.encode('utf-8')).hexdigest()
        except:
            return "unknown_state"

    def _extract_a11y_tree(self):
        """
        [New] 提取簡易版無障礙樹 (Accessibility Tree)
        幫助 LLM 理解那些 OmniParser 看不清楚的按鈕狀態 (如 aria-expanded, role=menuitem)
        """
        js_script = """
        function getA11yTree() {
            const tree = [];
            
            function traverse(el, depth) {
                if (!el) return;
                
                // 過濾隱藏元素
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
                
                // 判斷是否有語意價值
                const role = el.getAttribute('role');
                const ariaLabel = el.getAttribute('aria-label');
                const tagName = el.tagName.toLowerCase();
                
                // 關注互動元素
                const isInteractive = ['button', 'a', 'input', 'select', 'textarea', 'details', 'summary'].includes(tagName) ||
                                      (role && ['button', 'link', 'menuitem', 'tab', 'combobox', 'checkbox', 'switch'].includes(role));
                
                if (isInteractive) {
                    let info = `[${tagName.toUpperCase()}]`;
                    
                    // 獲取名稱
                    let name = ariaLabel || el.innerText || el.value || "";
                    name = name.slice(0, 50).replace(/[\\n\\t]/g, " ").trim();
                    if (name) info += ` "${name}"`;
                    
                    // 獲取狀態 (關鍵！)
                    if (el.getAttribute('aria-expanded') === 'true') info += " (EXPANDED)";
                    if (el.getAttribute('aria-checked') === 'true') info += " (CHECKED)";
                    if (el.disabled) info += " (DISABLED)";
                    
                    // 只有當元素有名字或特定狀態時才收錄，避免雜訊
                    if (name || info.includes('EXPANDED')) {
                        tree.push("  ".repeat(depth) + info);
                    }
                }
                
                // 遞迴
                for (let child of el.children) {
                    traverse(child, depth + (isInteractive ? 1 : 0));
                }
            }
            
            traverse(document.body, 0);
            // 只取前 100 行，避免 context 爆炸
            return tree.slice(0, 100).join('\\n');
        }
        return getA11yTree();
        """
        try:
            return self.driver.execute_script(js_script)
        except:
            return ""

    def _extract_page_content(self):
        try:
            # === Plan A: 抓取 Viewport 可見文字 (解決捲動後讀不到的問題) ===
            # 這段 JS 會過濾掉 display:none 以及 跑出螢幕範圍外的元素
            js_script = """
            function getVisibleText() {
                var walker = document.createTreeWalker(
                    document.body, 
                    NodeFilter.SHOW_TEXT, 
                    null, 
                    false
                );
                var node;
                var textLines = [];
                
                while(node = walker.nextNode()) {
                    var parent = node.parentNode;
                    var style = window.getComputedStyle(parent);
                    
                    // 1. 過濾隱藏元素
                    if (style && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                        var rect = parent.getBoundingClientRect();
                        
                        // 2. [核心] 檢查是否在 Viewport (視窗) 內
                        // 我們稍微放寬範圍 (擴大 500px)，確保不會切斷邊緣資訊
                        if (rect.bottom >= -500 && rect.top <= (window.innerHeight + 500)) {
                            var txt = node.nodeValue.trim();
                            if (txt.length > 0) {
                                // 嘗試保留一點結構 (如果是標題或區塊，加換行)
                                if (['H1','H2','H3','BUTTON','A','LI'].includes(parent.tagName)) {
                                    textLines.push("[" + parent.tagName + "] " + txt);
                                } else {
                                    textLines.push(txt);
                                }
                            }
                        }
                    }
                }
                return textLines.join('\\n');
            }
            return getVisibleText();
            """
            
            visible_text = self.driver.execute_script(js_script)
            
            if visible_text and len(visible_text) > 50:
                # 成功抓到視窗內容
                return visible_text[:3000] # 限制 Token
            
            else:
                # 如果 JS 抓不太到 (例如 Canvas 或是 Shadow DOM)，進入 Plan B
                raise Exception("Viewport text too short")

        except Exception as e:
            # === Plan B: 降級回原本的 Markdown 模式 ===
            print(f"⚠️ [Core] Viewport 提取受限 ({e})，切換為全頁 Markdown。")
            try:
                html_source = self.driver.page_source
                h = html2text.HTML2Text()
                h.ignore_links = True      
                h.ignore_images = True     
                h.ignore_emphasis = False  
                h.body_width = 0           
                
                markdown_content = h.handle(html_source)
                
                lines = [line.strip() for line in markdown_content.splitlines()]
                clean_content = "\n".join([line for line in lines if line])
                
                return clean_content[:3000]
            except:
                return self.driver.execute_script("return document.body.innerText")[:2000]
        
    def start_new_task(self, goal: str):
        """ 初始化任務並檢索記憶 """
        self.user_goal = goal
        self.history = []
        self.current_plan = ""
        self.scratchpad = {} # 每次新任務要清空
        print(f"🚀 [Core] 啟動新任務: {goal}")
        if self.memory_manager:
            try:
                self.rag_data = self.memory_manager.retrieve_relevant_memory(goal)
                print(f"[Core] 新任務: {goal}")
                if self.rag_data.get('success_path'): 
                    print("📚 [Memory] 已載入過去的成功策略！")
            except: pass
        try:
            generated_plan = planner_client.generate_plan(goal)
            if generated_plan:
                self.current_plan = generated_plan
                # 將計畫加入歷史紀錄，讓 Executor 一開始就知道全貌
                self.history.append(f"System Plan: {generated_plan}")
        except Exception as e:
            print(f"⚠️ Planner 呼叫失敗，將依賴 Executor 即興發揮: {e}")

    def get_history_window(self):
        if len(self.history) > self.max_history_len:
            return self.history[-self.max_history_len:]
        return self.history
    
    def check_success_with_tars(self):
        """
        [Updated] 使用 UI-TARS 進行終局驗證 (修正 Tuple 解包錯誤)
        """
        print("🕵️ [Core] 正在使用 UI-TARS 檢查任務是否已完成...")
        
        # 1. 準備截圖
        try:
            raw_png = self.driver.get_screenshot_as_png()
            img_b64 = base64.b64encode(raw_png).decode('utf-8')
            current_url = self.driver.current_url
        except Exception as e:
            print(f"⚠️ [Core] 截圖失敗，跳過 VQA: {e}")
            return False, None
        
        # 2. 呼叫 UI-TARS
        # [Fix] 這裡回傳的是 (bool, str)，必須解包
        is_found, answer_text = api_clients.call_eyes_ui_tars_vqa(self.user_goal, img_b64,current_url)
        
        # 3. 判斷結果
        if is_found:
            # 如果 UI-TARS 說找到了，且答案有效
            if answer_text and len(answer_text) > 0:
                print(f"🎉 [Core] UI-TARS 判定任務完成！答案: {answer_text}")
                return True, answer_text
            
        return False, None
    
    # [New] 主動式反射系統 (The Reflex Layer)
    def _reflex_system(self, elements_map, scale_x, scale_y):   
        if not elements_map: return False

        # 定義全網通用的「負面/關閉」關鍵字 (多語言支援)
        # 這些詞彙通常只出現在彈窗關閉鈕上，誤觸風險極低
        reflex_triggers = [
            # 英文
            "close", "no thanks", "not now", "skip", "skip ad", "dismiss", "maybe later", "reject", "x",
            # 中文
            "關閉", "跳過", "以後再說", "不", "不用了", "取消", "知道了",
            # 符號與特殊標記 (Visual-DOM 抓到的 aria-label)
            "close button", "close modal", "close ad", "close dialog"
        ]

        print("⚡ [Reflex] 正在掃描潛在干擾元素...")

        for el in elements_map:
            # 取得經 Visual-DOM 對齊後的文字 (轉小寫比對)
            text = el.get('text', '').lower().strip()
            
            # 條件 1: 文字精確匹配關鍵字
            # 條件 2: 或者是 "X" 這種極短的字符，且位於右上角 (需額外判斷座標，這裡先簡化)
            if text in reflex_triggers:
                print(f"🛡️ [Reflex] 偵測到阻礙元素: '{text}' (ID {el['id']})")
                print(f"⚡ [Reflex] 觸發脊髓反射 -> 立即消除！")
                
                # 計算座標
                cx = el['x'] + (el['w'] / 2)
                cy = el['y'] + (el['h'] / 2)
                
                # 執行點擊 (傳入邏輯座標)
                logic_x = int(cx / scale_x)
                logic_y = int(cy / scale_y)
                # 1. 嘗試標準點擊
                print(f"⚡ [Reflex] 嘗試點擊關閉...")
                click_success = browser_controller.perform_mouse_click(self.driver, logic_x, logic_y)
                
                # 2. 如果點擊失敗，或者我們想確保它死透 -> 執行 DOM 移除
                # (有些廣告點了沒反應，或者只是跳轉，移除是最保險的)
                if not click_success:
                    print("⚠️ 點擊失敗，啟動備案：強制移除元素！")
                    browser_controller.force_remove_element_by_coords(self.driver, logic_x, logic_y)
                
                # 3. 為了保險，就算點擊回傳 True，有時候彈窗還在
                # 我們可以選擇「點擊後再執行一次移除」，確保萬無一失
                # 但為了避免誤刪新出現的內容，我們先只做點擊+失敗移除
                
                time.sleep(1.5) # 等待畫面變化
                return True # 觸發重新感知

        return False
    
    def analyze_next_step(self):
        # 1. 環境準備
        browser_controller.wait_for_page_stability(self.driver)
        browser_controller.handle_window_policy(self.driver)
        #browser_controller.smart_wait_for_change(self.driver)
        page_state = browser_controller.get_page_state(self.driver)
        
        # --- [Upgrade 1] 死循環偵測 ---
        current_hash = self._get_page_hash()
        is_page_changed = (current_hash != self.last_page_hash)
        
        if not is_page_changed:
            self.same_state_action_count += 1
            print(f"⚡ [Core] 頁面狀態未變動 (Hash: {current_hash[:8]})...")
        else:
            self.same_state_action_count = 0
            self.last_page_hash = current_hash
            self.cached_elements_map = None # 清除快取
            
        # 如果連續 3 次在同一個畫面做動作沒反應，強制刷新
        if self.same_state_action_count >= 3:
            print("💀 [Core] 嚴重卡關！(Action Loop Detected)")
            
            # [New] 呼叫 Planner 重新規劃
            try:
                print("🧠 [Core] 請求 Planner 重新規劃戰略...")
                current_state_desc = f"Stuck at URL: {self.driver.current_url}. Recent History: {self.history[-3:]}"
                
                new_plan = planner_client.replan_task(self.user_goal, self.current_plan, current_state_desc)
                
                if new_plan:
                    print(f"📋 [Planner] 新計畫已生成: {new_plan}")
                    self.current_plan = new_plan
                    self.history.append(f"System: Plan Updated due to failure. New Plan: {new_plan}")
                    self.same_state_action_count = 0
                    return {"action": "wait", "thought": "Plan updated, re-evaluating."}
            except Exception as e:
                print(f"❌ Re-plan 失敗: {e}")

            # 如果 Re-plan 失敗或沒結果，才強制刷新
            print("🔄 強制刷新頁面...")
            self.driver.refresh()
            self.same_state_action_count = 0
            self.cached_elements_map = None
            return {"action": "wait", "thought": "Loop detected, refreshing page."}
        
        if self.history and "Scrolled" in self.history[-1]:
            print("🔄 [Core] 偵測到捲動，強制清除快取並等待渲染...")
            time.sleep(2.0) # 給瀏覽器一點時間重繪畫面
            self.cached_elements_map = None
            self.cached_img_size = None

            # 2. [New] 檢查是否陷入「無效捲動」 (連續捲動且內容未變)
            if len(self.history) >= 2 and "Scrolled" in self.history[-2]:
                # 如果連續兩次都是 Scrolled，我們需要更嚴格的檢查
                # 這裡做一個簡單的啟發式：透過 page_content 長度變化來判斷
                # 或者在傳給 Brain 的 prompt 裡加入警告
                print("⚠️ [Core] 偵測到連續捲動 (Consecutive Scrolling)...")
                
                # 這裡我們可以動態修改 user_goal 或者注入一個 System Hint
                # 但最簡單有效的方法是：修改接下來要傳給 LLM 的 elements_desc
                # (這部分會在下方 generate elements_desc 時生效，這裡先標記狀態)
                self.consecutive_scroll_warning = True 
            else:
                self.consecutive_scroll_warning = False
        else:
            self.consecutive_scroll_warning = False
        # -----------------------------

        # 2. 截圖與尺寸分析 (Retina Scaling Fix)
        # 這是 OmniParser 看世界的解析度 (物理像素)
        raw_png = self.driver.get_screenshot_as_png()
        image = Image.open(io.BytesIO(raw_png))
        img_w, img_h = image.size 
        img_size = (img_w, img_h)
        # 這是 Selenium 操作世界的解析度 (邏輯像素/CSS像素)
        # 必須使用 JS window.innerWidth/Height，這才是真正的 "Viewport"
        viewport_w = self.driver.execute_script("return window.innerWidth;") or 1920
        viewport_h = self.driver.execute_script("return window.innerHeight;") or 1080
        
        # 計算縮放比例
        scale_x = img_w / viewport_w
        scale_y = img_h / viewport_h
        print(f"[Core Debug] Image: ({img_w}, {img_h}), Viewport: ({viewport_w}, {viewport_h}), Scale: {scale_x:.2f}")
        
        # 抓取頁面文字，用於回答問題 (如 summarize, compare prices)
        try:
            page_content = self._extract_page_content()
            print(f"📖 [Core] 已提取頁面內容 (前 {len(page_content)} 字)")
        except Exception:
            page_content = "(Page content unavailable)"

        elements_map = []
        if not is_page_changed and self.cached_elements_map is not None:
            print("🚀 [Cache] 命中快取！跳過 OmniParser 呼叫。")
            elements_map = self.cached_elements_map
        else:
            # 沒命中，老實呼叫 API
            max_retries = 3
            for attempt in range(max_retries):
                print(f"👁️ [Vision] 呼叫 OmniParser (Attempt {attempt+1})...")
                omni_result = api_clients.call_eyes_omni_parser(raw_png)
                if omni_result:
                    elements_map = utils.convert_omni_data_to_elements(omni_result, img_size)
                    print(f"👁️ [Vision] OmniParser 捕捉到 {len(elements_map)} 個目標")
                if elements_map: break
                break 
            
            if elements_map:
                print(f"🔗 [Core] 正在執行 Visual-DOM 對齊...")
                query_coords = []
                for el in elements_map:
                    cx = el['x'] + (el['w'] / 2)
                    cy = el['y'] + (el['h'] / 2)
                    # 轉為邏輯像素
                    query_coords.append({"x": int(cx / scale_x), "y": int(cy / scale_y)})
                
                dom_details = browser_controller.batch_get_element_details(self.driver, query_coords)
                
                if dom_details and len(dom_details) == len(elements_map):
                    updated_count = 0
                    for i, el in enumerate(elements_map):
                        dom_info = dom_details[i]
                        dom_text = dom_info['text']
                        
                        # 1. 如果 DOM 有文字，優先使用 DOM (修正 OCR 錯誤)
                        if dom_text:
                            el['text'] = dom_text
                            el['tag'] = dom_info['tag'] # 修正 Tag
                            updated_count += 1
                        
                        # 2. [New] 語意增強：如果文字太短 (Icon/純符號)，嘗試補充 class/id
                        # 這能幫助 LLM 識別 "sort-btn", "search-icon", "menu-toggle" 等隱藏含義
                        if len(el['text']) < 5:
                            # 使用 .get() 以防 JS 端沒回傳這些欄位
                            raw_class = dom_info.get('class', '')
                            raw_id = dom_info.get('id', '')
                            
                            # 組合 Class 和 ID，並去除多餘空白
                            extra_meta = f"{raw_class} {raw_id}".strip()
                            
                            # 如果有找到屬性，且長度合理，就加到描述後面
                            if extra_meta:
                                # 截斷過長的 class (例如 Tailwind CSS 的長串 class)，只取前 40 字
                                el['text'] += f" [Attr: {extra_meta[:40]}]"

                        # 3. 附加原本的關鍵屬性 (如 href, src)
                        if dom_info.get('attr'):
                            el['text'] += f" ({dom_info['attr']})"
                            
                    print(f"✅ 對齊完成，增強了 {updated_count} 個元素的資訊。")
                else:
                    print("⚠️ 對齊失敗 (JS 回傳異常)，沿用 OmniParser 原始資料。")
            # ----------------------------------------------------
            if self._reflex_system(elements_map, scale_x, scale_y):
                # 如果反射系統觸發了動作 (例如點了關閉)，我們必須「重來」
                # 因為畫面已經變了 (彈窗沒了)，舊的截圖無效了
                print("🔄 [Reflex] 畫面已變更，重啟感知循環...")
                self.cached_elements_map = None # 清除快取
                # 回傳一個特殊的 Wait 訊號，讓外部迴圈繼續，自然會重新進入 analyze_next_step
                return {"action": "wait", "thought": "Reflex action executed (Popup closed). Refreshing perception."}
            # ============================================================
            if elements_map:
                self.cached_elements_map = elements_map

        if len(elements_map) > 50:
            print(f"📉 [Core] 元素過多 ({len(elements_map)})，執行智慧縮減...")
            # 簡單策略：保留前 40 個 (假設 OmniParser 已經按信心度排序) + 所有 Input
            important_elements = [el for el in elements_map if el['tag'] in ['input', 'textarea']]
            other_elements = [el for el in elements_map if el not in important_elements]
            elements_map = important_elements + other_elements[:40]
        # --- 分支判斷 ---

        # [New] 在準備大腦輸入時，提取 A11y Tree
        a11y_tree = self._extract_a11y_tree()
        print(f"🌲 [Core] A11y Tree 提取完畢 ({len(a11y_tree)} chars)")
        # 4. 準備大腦輸入 (文字化清單 + 圖片)
        tagged_b64, _ = utils.draw_som_on_image(raw_png, elements_map)
        
        elements_text_list = []
        if getattr(self, 'consecutive_scroll_warning', False):
            elements_text_list.append("⚠️ SYSTEM WARNING: You have scrolled twice. If the content looks the same, you might have reached the bottom. STOP scrolling and try to click or go back.")
        if elements_map and len(elements_map) > 0:
            for el in elements_map:
                clean_text = el['text'].replace('\n', ' ').strip()[:80] # 截斷過長文字
                elements_text_list.append(f"[ID {el['id']}] <{el['tag']}> {clean_text}")
        else:
            elements_text_list.append("(No interactive elements found)")
        
        elements_desc = "\n".join(elements_text_list)
        # [Mod] 將 A11y Tree 附加到 page_content 或 elements_desc 中
        # 這裡我們選擇附加到 page_content，因為它屬於「頁面資訊」的補充
        full_context_content = f"{page_content}\n\n=== ACCESSIBILITY TREE (Interactive Structure) ===\n{a11y_tree}"
        scratchpad_str = json.dumps(self.scratchpad, indent=2, ensure_ascii=False) if self.scratchpad else "No data collected yet."

        if len(self.history) > 2:
            is_success, answer = self.check_success_with_tars()
            if is_success:
                return {"action": "finish", "value": answer, "thought": "UI-TARS verified completion."}
        # 5. 呼叫大腦 (Brain)
        # 如果 OmniParser 完全沒抓到東西，elements_desc 會是空的，Brain 應該會決定 Grounding
        brain_response = api_clients.call_brain(
            self.user_goal, 
            self.get_history_window(), 
            page_state,
            tagged_b64,
            element_text_description=elements_desc,
            page_content=full_context_content, # 傳入 Markdown
            rag_data=self.rag_data,
            high_level_plan=self.current_plan,
            scratchpad_data=scratchpad_str
        )
        
        if not brain_response: return {"action": "wait", "thought": "Brain No Response"}
        if self.logger:
            # 準備要記錄的資料
            log_payload = {
                "page_url": self.driver.current_url,
                "planner_thought": brain_response.get("planner_thought", ""),
                "executor_thought": brain_response.get("executor_thought", ""),
                "action": brain_response.get("action"),
                "target": brain_response.get("target_description", ""),
                "value": brain_response.get("value", ""),
                "elements_found": len(elements_map) if 'elements_map' in locals() else 0,
                # 甚至可以記錄 page_content 的前 100 字，方便 debug
                "page_snippet": page_content[:200] if 'page_content' in locals() else ""
            }
            # 這裡的 step 數可以從 history 長度推算
            self.logger.log_step(len(self.history) + 1, log_payload)
        # 6. 動作分流 (Action Dispatch)
        # ================= [Critical Fix] 絕對初始化區塊 =================
        # 這裡的變數定義必須在所有 if/else 之外，防止 UnboundLocalError
        action = brain_response.get("action", "wait")
        target_desc = brain_response.get("target_description", "")
        value = brain_response.get("value", "")
        
        # 安全取得 target_id (確保是整數)
        raw_id = brain_response.get("element_id", 0)
        try:
            target_id = int(raw_id)
        except:
            target_id = 0
            
        # 安全取得 coords (確保是 Tuple/List)
        coords = brain_response.get("coords")
        
        # 初始化 target_text (避免 execute_action 報錯)
        target_text = "" 
        # ================================================================

        # ----------------------------------------------------------------
        # [Logic] 自動救援邏輯 (Auto-Rescue)
        # ----------------------------------------------------------------
        should_force_grounding = False
        
        # 條件 1: 想要操作但 ID 為 0
        if action in ["click", "type"] and target_id == 0:
            print("🤖 [Core] LLM 想操作但找不到 ID (ID 0)，強制切換 UI-TARS！")
            should_force_grounding = True
            
        # 條件 2: 陷入 Wait 死循環
        if action == "wait" and self.same_state_action_count > 1:
            print("🤖 [Core] 陷入 Wait 死循環，強制切換 UI-TARS！")
            should_force_grounding = True
            if not target_desc or target_desc == "Unknown Target":
                target_desc = self.user_goal

        # 執行強制轉換
        if should_force_grounding:
            action = "grounding"
            if not target_desc or target_desc == "Unknown Target":
                # 啟發式目標補全
                url_lower = self.driver.current_url.lower()
                if "wolfram" in url_lower or "google" in url_lower:
                    target_desc = "Search input bar"
                else:
                    target_desc = "Search bar or Main interactive element"

        # ----------------------------------------------------------------
        # 6. 動作分流 (Action Dispatch)
        # ----------------------------------------------------------------
        
        # [Case A] Finish
        if action == "finish":
            brain_response["is_finished"] = True
            if value:
                self.history.append(f"Final Answer: {value}")
            return brain_response
        
        
        # [Case B] Retrieve
        if action == "retrieve":
            # ... (保留您的 Retrieve 邏輯) ...
            if self.memory_manager:
                try:
                    new_rag = self.memory_manager.retrieve_relevant_memory(target_desc or self.user_goal)
                    self.rag_data = new_rag
                    if new_rag.get('success_path'):
                        print("📚 [Memory] 已動態載入新策略！")
                except: pass
            return {"action": "wait", "thought": "Knowledge retrieved."}

        # [Case C] Grounding (UI-TARS)
        if action == "grounding":
            print(f"🧠 [Brain] 啟用 UI-TARS 救援，目標: {target_desc}")
            img_b64 = base64.b64encode(raw_png).decode('utf-8')
            tars_result = api_clients.call_eyes_ui_tars_grounding(target_desc, img_b64)
            
            if tars_result and 'coords' in tars_result:
                raw_coords = tars_result['coords']
                logic_x = int(raw_coords[0] / scale_x)
                logic_y = int(raw_coords[1] / scale_y)
                
                final_action = "click"
                is_input_field = any(k in target_desc.lower() for k in ["search", "input", "box", "field", "text", "bar"])
                if value: final_action = "type"
                elif is_input_field:
                    final_action = "type"
                    # 自動填入 value (如果 Brain 沒給)
                    if not value: 
                        value = self.user_goal.replace("搜尋", "").replace("Search", "").replace("Find", "").replace("Calculate", "").strip()
                        print(f"🤖 [Core] 自動補全輸入值: '{value}'")
                return {
                    "action": final_action,
                    "coords": (logic_x, logic_y),
                    "value": value,
                    "thought": "Grounding success.",
                    "target_desc": target_desc,
                    "target_text": target_desc # 用描述當作文字救援
                }
            return {"action": "scroll", "thought": "Grounding failed."}

        # [Case D] Standard ID Interaction
        if action in ["click", "type"]:
            # [Fix] 使用前面初始化好的 target_id，不要再從 brain_response get 了
            target_el = next((e for e in elements_map if str(e['id']) == str(target_id)), None)
            
            if target_el:
                # 計算中心點
                center_x = target_el['x'] + (target_el['w'] / 2)
                center_y = target_el['y'] + (target_el['h'] / 2)
                
                # 更新 brain_response (這些資料會傳給 execute_action)
                brain_response["coords"] = (int(center_x / scale_x), int(center_y / scale_y))
                
                # [Fix] 確保 target_text 存在
                target_text = target_el.get('text', '')
                brain_response["target_text"] = target_text
                
                brain_response["target_desc"] = f"ID {target_id} ({target_text})"
                brain_response["action"] = action # 確保 action 正確
            else:
                print(f"⚠️ [Core] ID {target_id} 不存在，轉為 Wait。")
                brain_response["action"] = "wait"

        # [Case E] 其他動作 (Scroll, Back...) 直接回傳
        return brain_response

    def execute_action(self, action_data, target_desc=None, value=None, auto_submit=False, target_text=None):
        """
        [Updated] 執行動作 (整合文字救援與擬人化)
        """
        # 1. 參數解析與適配 
        if isinstance(action_data, dict):
            action = action_data.get("action")
            thought = action_data.get("thought", "")
            value = action_data.get("value")
            coords = action_data.get("coords") # (x, y)
            target_id = action_data.get("element_id")
            
            # [Fix 1] 提取 target_text (這是文字救援的關鍵)
            # 從 analyze_next_step 傳過來的資料中獲取
            target_text = action_data.get("target_text", target_text)
            
            target_desc = action_data.get("target_desc", target_desc)
            if not target_desc:
                target_desc = f"Element ID {target_id}" if target_id else "Unknown Target"
            
            # 順便提取 auto_submit
            auto_submit = action_data.get("submit", auto_submit)
        else:
            # 舊版介面相容
            action = action_data
            thought = ""
            coords = None
            if not target_desc: target_desc = "Unknown Target"

        # Log 顯示目標，方便除錯
        print(f"🤖 [Executor] {action} ({target_desc}) | Val: {value} | Text: {target_text}")

        # --- 2. 執行邏輯 ---
        if action == "finish":
            return True, "任務完成"
            
        if action == "scroll":
            # 這裡呼叫我們新改的具備狀態感知的 perform_scroll
            success = browser_controller.perform_scroll(self.driver, "down")
            if success:
                self.history.append("Scrolled down")
                print("🔄 [Core] 捲動發生，強制清除視覺快取 (Force Refresh)...")
                self.cached_elements_map = None 
                self.last_page_hash = "" 
                return True, "捲動完成"
            else:
                self.history.append("Scroll FAILED (End of page)")
                return False, "已達底部"
            
        if action == "goto_url":
            success = browser_controller.perform_goto_url(self.driver, value)
            if success:
                self.history.append(f"Jumped to {value}")
                self.cached_elements_map = None
                self.last_page_hash = ""
                return True, "跳轉成功"
            return False, "跳轉失敗"

        if action == "wait":
            print("⏳ [Executor] 執行等待 (3s)...")
            time.sleep(3)
            return True, "等待"
        
        if action == "extract_content":
            # 1. 決定 Key
            key = target_desc if target_desc else "Extracted Data"
            # 2. 決定 Value (從 action_data 來的)
            data = value

            # 3. 執行儲存 (寫入 Agent 的記憶體)
            if data:
                self.scratchpad[key] = data
                print(f"📝 [Core] 已寫入筆記本: {key} = {data}")
                self.history.append(f"Saved to Memory: {key} = {data}")
                
                # [Fix] 這裡必須回傳 Dict，不能回傳 Tuple
                # action 設為 "wait" 是為了讓 Agent 存完資料後，停下來思考下一步該怎麼用這些資料
                return {
                    "success": True, 
                    "message": f"已記錄: {key}",
                    "action": "wait", 
                    "value": data
                }
            else:
                return {
                    "success": False, 
                    "message": "提取失敗 (缺少 value)",
                    "action": "wait"
                }

        if action == "go_back":
            print("🔙 [Browser] 執行 Back 操作...")
            self.driver.back()
            self.history.append("Navigated Back")
            self.cached_elements_map = None
            self.last_page_hash = ""
            browser_controller.smart_wait_for_change(self.driver) # 使用 smart wait 確保載入
            return True, "返回上一頁"

        # --- 3. SoM / UI-TARS 精確操作 ---
        if (action == "click" or action == "type") and coords:
            # [Optimization] 移除 +5 偏移
            # 因為 analyze_next_step 已經計算了精確中心點，
            # 且 human_mouse 內部會有隨機偏移，這裡再加固定偏移反而會造成誤差。
            x, y = int(coords[0]), int(coords[1])
            
            success = False
            
            if action == "click":
                # [Critical] 傳遞 target_text 給 perform_mouse_click 以啟用文字救援
                success = browser_controller.perform_mouse_click(
                    self.driver, 
                    x, y, 
                    expect_change=True, 
                    target_text=target_text
                )
                if success:
                    self.history.append(f"Clicked '{target_desc}'")
            
            elif action == "type":
                # [Critical] perform_type 內部已經整合了:
                # 1. 點擊(expect_change=False) 2. 輸入 3. 動態等待 4. Enter
                success = browser_controller.perform_type(self.driver, x, y, value)
                if success:
                    self.history.append(f"Typed '{value}' into '{target_desc}'")
                    # 這裡不需要再手動送 Enter 了，因為 perform_type 已經做掉了
                    # 但為了記錄，我們可以加上這行 Log
                    self.history.append("Auto-submitted via Enter")

            if success:
                self.cached_elements_map = None
                # 這裡不需要額外的 wait_for_page_load，因為 controller 內部已經有了 smart_wait
                return True, f"{action} 成功"
            else:
                return False, f"{action} 執行失敗 (操作無效)"

        return False, f"未知的動作或缺失座標: {action}"

    def verify_completion(self):
        """ 驗證任務是否完成 (DOM + Vision) """
        keyword = self.user_goal 
        
        # 1. 快速 DOM 檢查
        if browser_controller.check_page_content_match(self.driver, keyword):
            self._save_success()
            return True, "DOM 關鍵字驗證通過"
        
        # 2. 深度視覺驗證 (Visual VQA)
        print("[Core] 啟用視覺驗證 (VQA)...")
        img_bytes = self.driver.get_screenshot_as_png()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        
        is_pass, reason = api_clients.call_visual_verification(self.user_goal, img_b64)
        
        if is_pass:
            self._save_success()
            return True, f"視覺驗證通過: {reason}"
        else:
            self.history.append(f"System: Verification FAILED. Reason: {reason}")
            return False, reason

    def handle_failure(self, reason: str):
        """ 失敗時的反思與記錄 """
        print(f"[Core] 任務失敗，正在反思: {reason}")
        insight = api_clients.call_reflexion(self.user_goal, self.history, reason)
        sanitized_history = utils.sanitize_history(self.history)
        self.memory_manager.add_memory(self.user_goal, sanitized_history, outcome="failure", insight=insight)

    def _save_success(self):
        """ 成功時的記錄 """
        sanitized_history = utils.sanitize_history(self.history)
        self.memory_manager.add_memory(self.user_goal, sanitized_history, outcome="success")
        browser_controller.cleanup_tabs(self.driver)

    def check_login_status(self, initial_url):
        try:
            if self.driver.current_url != initial_url: return True
        except: pass
        return False