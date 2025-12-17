# api_clients.py
# [更新] V11 - 支援 RAG 注入與 Reflexion 反思

import requests
import json
import re
from openai import OpenAI 
from config import (GPT_OSS_URL, GPT_OSS_MODEL_NAME, USE_OPENAI_API, 
                    OPENAI_API_KEY, OPENAI_MODEL_NAME, OMNIPARSER_API_URL, UI_TARS_API_URL)
from utils import parse_omni_coordinates, parse_coords_from_string, parse_json_from_string

# [New] 強健的 JSON 解析器 (取代 utils.parse_json_from_string)
def robust_json_parse(text):
    """
    嘗試從髒亂的 LLM 回覆中提取並修復 JSON。
    支援 ```json 區塊提取與常見語法錯誤修復。
    """
    if not text: return None
    try:
        # 1. 嘗試直接解析
        return json.loads(text)
    except: pass

    # 2. 提取 Markdown Code Block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try: return json.loads(match.group(1))
        except: pass
    
    # 3. 尋找最外層的大括號
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            # 嘗試修復單引號轉雙引號 (簡單版)
            clean_json = match.group(1).replace("'", '"') 
            return json.loads(clean_json)
        except: pass

    print(f"❌ JSON Parse Failed. Raw text: {text[:100]}...")
    return None

def call_brain(user_goal: str, history: list, page_state: dict, som_image_b64: str, rag_data: dict = None, element_text_description: str = "", page_content: str = "", high_level_plan: str = "", scratchpad_data: str = "") -> dict | None:
    """
    [Updated] 統一的大腦入口。
    整合：SoM 視覺 + CoT 推理 + RAG 記憶注入 + OpenAI/Local 切換。
    """
    
    # 1. 準備歷史紀錄
    history_str = "\n".join([f"- {step}" for step in history[-5:]]) if history else "(No recent history)"
    
    # 2. 準備 RAG 記憶區塊 (Agentic RAG)
    rag_section = ""
    if rag_data:
        if rag_data.get('success_path'):
            rag_section += f"\n[💡 Past Success Strategy]\n(Use this as a high-priority reference)\n{rag_data['success_path']}\n"
        
        if rag_data.get('warnings'):
            warnings_str = "\n".join([f"- {w}" for w in rag_data['warnings']])
            rag_section += f"\n[⚠️ Mistakes to Avoid]\n{warnings_str}\n"

    system_hint = page_state.get('system_hint', '')

    # 3. 準備高層次計畫區塊
    plan_section = ""
    if high_level_plan:
        plan_section = f"""
    === 📋 STRATEGIC PLAN (From Planner Agent) ===
    {high_level_plan}
    
    **CRITICAL INSTRUCTION:** - You are the EXECUTOR. Your job is NOT to re-plan, but to execute the current step of the plan above.
    - Compare the [History] with the [Strategic Plan] to decide which step you are currently on.
    ==============================================
    """
    else:
        plan_section = "\n(No high-level plan available. You must plan and execute autonomously.)\n"
        
    #JSON issue fix
    system_prompt = """
    You are an advanced Browser Automation Agent operating in a "Planner-Executor" cognitive architecture.
    
    **Cognitive Process (Algorithm of Thoughts):**
    Output your reasoning in two phases:
    
    **PHASE 1: THE PLANNER (High-Level Strategy)**
    - Analyze the User Goal and History.
    - **Strategic Knowledge (Handling Complex UI):**
        - **Date Pickers:** To select a date (e.g., 'March 20'), DO NOT try to type it blindly. 
          1. Click the calendar input to open it. 
          2. Check if the target month is visible. If not, click 'Next Month' button until it is. 
          3. Use "grounding" to click the specific day number.
        - **Reading Tasks:** If the goal asks for information (price, summary), read the [Page Content] section carefully.
        - **Scanning:** When viewing search results, DO NOT just click the first item. Scan the [Interactive Elements List] for text that matches specific constraints (e.g., "4.5 stars", "100 reviews"). Pick the BEST candidate.
        - **Verifying:** After clicking a result, READ the [Page Content] to confirm it meets all user criteria (e.g., "Is it for 6 people?"). 
          - IF MATCH: Use action "finish".
          - IF MISMATCH: Use action "go_back" to return to the search results and pick another one.
    
    **PHASE 2: THE EXECUTOR (Low-Level Grounding)**
    - Look at the [Interactive Elements List] and [Page Content].
    - **Clicking Strategy:**
        - To view a recipe/item, click the **Image** or the **Big Title Text**.
        - **AVOID** clicking small icons like hearts, bookmarks, or plus signs (these usually trigger login).
    - **CRITICAL DECISION BRANCH:**
        - **Path A (Direct Hit):** If a matching ID exists, use action "click" or "type".
        - **Path B (Vision Grounding):** If list is bad/empty but target should be there (e.g. specific date in calendar) -> action: "grounding".
        - **Path C (Backtrack):** If the current page does not meet the goal constraints -> action: "go_back".
        - **Path D (Scroll):** If content is hidden -> action: "scroll".
        - **Path E (Retrieve Knowledge):** If stuck -> action: "retrieve".
        - **Path F (Data Extraction):** If you see important data -> action: "extract_content".
        - **Path G (Finish with Answer):** If goal is met AND data is saved/verified.
          -> action: "finish"
          -> value: "The answer to the user's question" (e.g., "The price is $120", "The summary is...")

    **PHASE 3: STRATEGIC KNOWLEDGE (How to interact?)**
    - **Search Verification:** - After `type` + `Enter`: Look for "Results for..." or a list of items.
      - If page looks the same, DO NOT type again. Try `click` the search button explicitly.
    - **Dropdowns & Sort:**
      - You cannot click "Low to High" if the dropdown is closed.
      - Action 1: Click "Sort by" button -> Wait.
      - Action 2: Click the specific option.
    - **List Accumulation (Find X items):**
      - Do NOT finish after finding just one.
      - Pattern: Click Item 1 -> Verify -> Go Back -> Click Item 2 -> Verify -> Go Back.
      - **Scratchpad:** In your `executor_thought`, explicitly state: "I have found X items so far. I need Y more."
    
    - **[NEW] DATA COLLECTION PROTOCOL (CRITICAL):**
      1. **Search:** Perform the query (e.g., "Canada population 2020-2023").
      2. **Verify:** Do you see the numbers/chart on the screen?
      3. **EXTRACT (The most important step):** - **STOP.** Do NOT navigate away yet.
         - **EXECUTE** `extract_content` to save the data to your memory.
         - Example: `target_description`: "Population 2020-2023", `value`: "2020: 38.0M, 2021: 38.2M..."
      4. **Review Memory:** Look at [📝 Current Scratchpad] in the user prompt. Is the data there?
         - IF YES -> Proceed to calculation or finish.
         - IF NO -> You CANNOT finish. You must extract first.

    - **Date Verification:**
      - If the list doesn't show dates, you MUST click into the item to check its "Created/Updated" date.
      - If the date is too old, use `go_back` immediately.
    - **Login Traps:** If you encounter a "Sign In" or "Register" page AND the user did not ask to log in:
          -> **IMMEDIATELY use action "go_back"**. Do NOT try to guess credentials.
    - **Date Pickers (CRITICAL):** 1. Click the input to open the calendar.
        2. **WAIT** and look for the month. 
        3. If specific day is NOT visible, click 'Next Month' arrow.
        4. **Do NOT type dates** unless it's a simple text field. Always use clicks.

    **CRITICAL VERIFICATION RULES (Metric Disambiguation):**
    - **Review Count vs. Rating Count:**
        - `(123)` or `1.2k ratings` = **Rating Count** (Votes).
        - `84 Reviews` or `Comments` = **Review Count** (Text).
    - **DO NOT** confuse them. If user asks for "100 Reviews", finding "(116)" stars but only "84 Reviews" is a **FAILURE**. You must "go_back".
    - **Strict Comparison:** 84 is NOT > 100. Be pedantic with numbers.

    **Data Extraction Rules (CRITICAL for 'type' action):**
    - You must EXTRACT only the specific search query or data. Do NOT include instructions.
    - **Search Query Distillation (KEYWORD ONLY):**
        - If the goal contains constraints (e.g., "rating 4.5+", "100 reviews", "under $50"), **DO NOT type them into the search bar**.
        - Search engines prefer simple keywords. You will apply filters LATER.
    - **Strict Constraint Check:**
        - Before using action "finish", you must explicit compare the FOUND value vs. the REQUIRED value in your thought process.
        - Thought: "Found '84 Reviews'. User wants '> 100'. 84 is NOT greater than 100. Mismatch. I must go back."

    
    **COMMANDS (Action Space):**
    - **click**: Click on a specific element ID.
    - **type**: Type text into an input field (ID required).
    - **scroll**: Scroll down to see more content.
    - **wait**: Wait for page load or animation.
    - **go_back**: Return to the previous page (use when results are bad).
    - **grounding**: Use UI-TARS to find an element by description (when ID is missing).
    - **extract_content**: 
      - **PURPOSE:** Save data to your internal memory (Scratchpad).
      - **ARGUMENTS:** - `target_description`: The label/key (e.g., "2020 Population", "Price of Hotel A").
        - `value`: The actual data extracted from the screen (e.g., "38 million", "$199").
      - **MANDATORY USE:** You MUST use this action immediately when you see the requested data on screen. 

    **Response Format (JSON Only):**
    You must respond with a RAW JSON object. Do not include markdown formatting (```json), explanations, or conversational filler.
    
    **JSON Schema:**
    {
        "planner_thought": "Phase 1...",
        "executor_thought": "Phase 2...",
        "action": "click" | "type" | "scroll" | "wait" | "goto_url" | "finish" | "grounding" | "retrieve" | "go_back" | "extract_content",
        "target_description": "Search Input Bar",
        "element_id": 123,  // Integer ID from the interactive list. Use 0 if using grounding.
        "value": "text input OR final answer OR extracted data",
        "verification_evidence": "Found Rating: 4.6 (116), Found Reviews: 84. Goal: >100 Reviews. Result: FAIL" 
    }

    **CRITICAL RULES:**
    1. **NO Text Actions:** Do not output "Action: type -> Target: ...". ONLY JSON.
    2. **ID Priority:** Always prefer `element_id` from the list. Use `grounding` only if ID is missing.
    3. **Data Protocol:** If you see the answer, use `extract_content` FIRST, then `finish` in the next turn.

    **FEW-SHOT EXAMPLES (JSON ONLY):**

    User Goal: "Search for iPhone 15"
    {
        "planner_thought": "I need to search for the product.",
        "executor_thought": "I see the search bar (ID 5). I will type the query.",
        "action": "type",
        "target_description": "Search Input",
        "element_id": 5,
        "value": "iPhone 15"
    }

    User Goal: "Get the price of the hotel"
    {
        "planner_thought": "The price is visible on screen.",
        "executor_thought": "I see '$199' next to the hotel name. I will save this.",
        "action": "extract_content",
        "target_description": "Hotel Price",
        "element_id": 0,
        "value": "$199"
    }
    """
    
    # 4. 建構 User Content (當前情境)
    user_content = f"""
    [Goal]: {user_goal}
    [Current URL]: {page_state.get('url')}
    [Title]: {page_state.get('title')}
    {system_hint}
    {plan_section}
    [History]:
    {history_str}
    {rag_section}

    [Interactive Elements List] (From OmniParser):
    {element_text_description}

    [Page Content] (Text observed on page):
    {page_content[:1000]}
    
    [📝 Current Scratchpad (Collected Data)]:
    {scratchpad_data}
    (This is your short-term memory. Use it to check what you have already found.)

    Based on the strategy, what is the next step?
    """

    # 5. 呼叫模型
    if USE_OPENAI_API:
        return _call_openai(system_prompt, user_content, som_image_b64)
    else:
        return _call_local_llm(system_prompt, user_content, som_image_b64)
    

def _call_openai(system_prompt, user_content, image_b64):
    print(f"🧠 [Brain] Calling OpenAI ({OPENAI_MODEL_NAME})...")
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]}
            ],
            max_tokens=1024, # 增加 token 數以容納 CoT
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        return robust_json_parse(content)
    except Exception as e:
        print(f"❌ OpenAI Error: {e}")
        return None

def _call_local_llm(system_prompt, user_content, image_b64):
    print(f"🧠 [Brain] Calling Local GPT-OSS ({GPT_OSS_MODEL_NAME})...")
    
    # 將 System prompt 與 User content 合併 (針對不支援 System Role 的本地模型)
    prompt = f"{system_prompt}\n\n======\n\n{user_content}"
    
    payload = {
        "model": GPT_OSS_MODEL_NAME,
        "prompt": prompt,
        "images": [image_b64], 
        "stream": False,
        "options": {"temperature": 0.0, "top_p": 0.9, "max_tokens": 1024} 
    }
    
    try:
        response = requests.post(GPT_OSS_URL, json=payload, timeout=60)
        response.raise_for_status()
        text_response = response.json().get('response', '')
        return robust_json_parse(text_response)
    except Exception as e:
        print(f"❌ Local LLM Error: {e}")
        return None


def call_reflexion(user_goal: str, history: list, error_reason: str) -> str:
    """
    (New) 反思機制：分析失敗原因並產生 Insight
    """
    print("🤔 [Reflexion] 正在進行自我反思...")
    history_str = "\n".join([f"- {step}" for step in history])
    
    prompt = f"""
    任務失敗了。請回顧這段操作歷史與錯誤原因。
    
    [目標] {user_goal}
    [歷史] {history_str}
    [錯誤] {error_reason}
    
    請總結一條簡短教訓 (Insight)，例如："不要在首頁重複點擊 Logo"。
    """
    
    payload = {
        "model": GPT_OSS_MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "max_tokens": 200}
    }
    
    try:
        response = requests.post(GPT_OSS_URL, json=payload, timeout=120)
        insight = response.json()['response'].strip()
        print(f"💡 [Insight] {insight}")
        return insight
    except Exception as e:
        print(f"❌ 反思失敗: {e}")
        return "無法產生反思"

def call_visual_verification(user_goal: str, image_b64: str) -> tuple[bool, str]:

    print(f"--- 正在呼叫 Visual Verification (VQA) ---")
    
    # 簡化 Prompt，不要求過多解釋，專注於 JSON 結構
    prompt = f"""
    Verify if the user's goal is achieved in this screenshot.
    User Goal: "{user_goal}"
    Context: Desktop Browser.
    Instructions:
    1. Check if the main content matches the goal.
    2. **Do NOT translate proper names** (e.g., maintain '凝風', 'Roger9527').
    3. **Goal Check**:
       - If goal is "Play/Watch", is a video player visible? (Channel page is NOT enough).
       - If goal is "Find", is the profile/info visible?
    4. **Time Check**: If the user asked for the "latest" or "newest" video, check the upload date (e.g., "2 days ago", "1 hour ago"). 
       - If the video says "X years ago" or "X months ago", it is likely WRONG (unless the channel hasn't updated in years).
    5. If the goal is to play a video, checking if the video title OR the **Uploader/Channel Name** matches is sufficient.
    6. Ignore Ads.

    Output valid JSON ONLY:
    {{
        "pass": true,
        "reason": "Found video titled One OK Rock"
    }}
    OR
    {{
        "pass": false,
        "reason": "Page is empty or irrelevant"
    }}
    """
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "/app/model", 
        "max_tokens": 100, # 限制 Token 數，防止模型廢話導致亂碼
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]}
        ]
    }
    try:
        response = requests.post(UI_TARS_API_URL, headers=headers, json=payload, timeout=60)
        text_response = response.json()['choices'][0]['message']['content'].strip()
        print(f"🕵️ [VQA Result]: {text_response}")
        
        # 嘗試解析
        result = robust_json_parse(text_response)
        
        # 如果解析成功
        if result and "pass" in result:
            return result["pass"], result.get("reason", "Verified")
            
        # [防亂碼兜底策略] 如果 JSON 解析失敗，用簡單的關鍵字判斷
        lower_text = text_response.lower()
        if "true" in lower_text and "pass" in lower_text:
            return True, "Parsed from text (JSON failed)"
        elif "false" in lower_text:
            return False, "Parsed from text (JSON failed)"
            
        return False, "Invalid VQA response format"
        
    except Exception as e:
        print(f"❌ Verification Failed: {e}")
        return False, str(e)


def call_eyes_omni_parser(image_bytes: bytes) -> dict | None:
    print(f"--- 正在呼叫 OmniParser ---")
    files = {'file': ('image.png', image_bytes, 'image/png')}
    params = {'box_threshold': 0.05, 'iou_threshold': 0.1, 'use_paddleocr': True}
    try:
        response = requests.post(OMNIPARSER_API_URL, files=files, params=params, timeout=60)
        response.raise_for_status()
        result = response.json()
        if result.get('status') == 'success':
            result['label_coordinates'] = parse_omni_coordinates(result.get('label_coordinates', []))
            return result
        return None
    except Exception as e:
        print(f"❌ OmniParser 呼叫失敗: {e}")
        return None

def call_eyes_ui_tars_grounding(sub_task: str, image_b64: str) -> dict | None:
    print(f"--- 正在呼叫 UI-TARS (定位) ---")
    prompt = f"""
    Task: Locate the exact center coordinates [x, y] for the UI element described as: "{sub_task}".
    
    Constraints:
    1. **Interactable Only:** The target MUST be clickable or typable (Input, Button, Link).
    2. **Visual Grounding:** Ignore identifying text if it's not a button. Focus on the control itself.
    3. **Center Point:** Return the center of the element, not the edge.
    4. **Format:** Return ONLY the coordinate tuple/list, e.g., [500, 300]. Do not output explanations.
    """
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "/app/model", 
        "max_tokens": 100, 
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]}
        ]
    }
    try:
        response = requests.post(UI_TARS_API_URL, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        text_response = response.json()['choices'][0]['message']['content']
        print(f" UI-TARS 回應: {text_response}")
        return robust_json_parse(text_response)
    except Exception as e:
        print(f"❌ UI-TARS 呼叫失敗: {e}")
        return None

def call_eyes_ui_tars(prompt: str, image_b64: str) -> str | None:
    return None 

def call_popup_killer(image_b64: str) -> dict | None:
    print(f"--- 正在呼叫 Popup Killer ---")
    prompt = """
    Detect if there is a popup, ad, or cookie consent banner blocking the view.
    If yes, find the 'Close', 'X', 'No thanks', 'Reject', or 'Skip' button.
    Return the center coordinates in format: Close button at [x, y].
    If no popup is found, return "No popup".
    """
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "/app/model", 
        "max_tokens": 100,
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]}
        ]
    }
    try:
        response = requests.post(UI_TARS_API_URL, headers=headers, json=payload, timeout=60)
        text_response = response.json()['choices'][0]['message']['content']
        if "No popup" in text_response:
            return None
        return robust_json_parse(text_response) 
    except Exception:
        return None

def call_eyes_ui_tars_vqa(user_goal: str, image_b64: str, current_url: str = "") -> tuple[bool, str]:
    """
    [Updated] UI-TARS VQA 模式
    用途：不僅驗證是否成功，還負責「提取答案」給 Agent 直接結束任務。
    """
    print(f"👁️ [UI-TARS] 正在進行視覺終局驗證 (VQA)...")
    
    # [Mod] Prompt 重構：從「檢查 JSON」改為「直球對決提取答案」
    # 這是為了解決 Wolfram Alpha 這類「看到圖表但 Agent 讀不到字」的窘境
    prompt = f"""
    You are an intelligent visual assistant.
    Your task is to extracting information from the screenshot to answer the User Goal.
    
    User Goal: "{user_goal}"
    Current URL: "{current_url}"
    
    **STEP 1: DOMAIN VERIFICATION (Pre-check)**
    - Does the [Current URL] match the specific website requested in the [User Goal]?
    - Example: If goal is "Find on Amazon", but URL is "google.com", output "NO".
    - **CRITICAL:** If the goal explicitly names a platform (e.g., "Wikipedia", "Wolfram", "Amazon") and the URL does not match, output "NO" immediately.
    - If the goal does NOT specify a website, proceed to Step 2.

    **STEP 2: VISUAL ANALYSIS & EXTRACTION (Your Instructions)**
    1. Analyze the screenshot carefully. Look for charts, big numbers, or result summaries.
    2. **IF ANSWER FOUND:** - Output the answer DIRECTLY and CONCISELY. 
       - Example: "38.01 million", "$199", "The weather is sunny".
       - Do NOT output "Yes" or "I found it". Just the data.
    3. **IF ACTION COMPLETED:**
       - If the goal was an action (e.g. "Sort by price") and the UI reflects this change, output "Task Completed".
    4. **IF NOT FOUND:** - Output exactly "NO".
    """
    
    # 沿用你的變數設定
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "/app/model", # 請確認這是你的 UI-TARS 模型路徑
        "max_tokens": 128,     # 我們只需要簡短答案，不需要長篇大論
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]}
        ],
        "temperature": 0.1 # 低隨機性，追求精確
    }

    try:
        # 沿用你的 requests 邏輯
        response = requests.post(UI_TARS_API_URL, headers=headers, json=payload, timeout=45)
        
        if response.status_code == 200:
            text_response = response.json()['choices'][0]['message']['content'].strip()
            print(f"👁️ [VQA Result]: {text_response}")
            
            # [Logic] 解析邏輯：不是 JSON 了，而是關鍵字判斷
            
            # 1. 失敗狀況
            if text_response.upper() == "NO" or "NOT FOUND" in text_response.upper():
                return False, "VQA: Answer not visible"
            
            # 2. 成功狀況 (回傳 True 和 提取到的答案)
            # 過濾掉一些常見的廢話
            clean_answer = text_response.replace("The answer is", "").strip()
            if len(clean_answer) > 0:
                return True, clean_answer
                
            return False, "VQA: Empty response"
            
        else:
            print(f"❌ [UI-TARS] API Error: {response.status_code} - {response.text}")
            return False, f"API Error {response.status_code}"

    except Exception as e:
        print(f"❌ Verification Failed: {e}")
        return False, str(e)