# planner_client.py
import requests
import json

# 設定你的 Server IP 和 Port
# 請確保這裡與你的 Docker 容器設定一致
PLANNER_API_URL = "http://yourserverip:port/v1/chat/completions"
MODEL_NAME = "deepseek-reasoner" 

def generate_plan(user_goal: str) -> str:
    """
    [Initial Planner]
    任務啟動時呼叫，生成初始的高層次執行計畫。
    已加入「批量查詢」優化策略。
    """
    print(f"🧠 [Planner] 正在呼叫 DeepSeek-R1 生成初始計畫... (Goal: {user_goal})")
    
    system_prompt = """
    You are an expert Web Automation Planner. 
    Your goal is to break down a complex user request into a clear, logical, step-by-step plan.
    
    **STRATEGY FOR DATA AGGREGATION (CRITICAL):**
    - **Batch Querying:** If the user wants data for a range (e.g., "population 2020-2023") or multiple items:
      - **ALWAYS PREFER** a single search query that retrieves all data at once (e.g., "Canada population 2020 to 2023").
      - Search engines (Google, Wolfram Alpha) handle ranges well.
      - **DO NOT** generate separate steps for each year (e.g., "Step 1: Search 2020", "Step 2: Search 2021") unless the website specifically requires it.
      - This reduces navigation errors and prevents memory loss.

    **Guidelines:**
    1. Analyze the user's goal.
    2. Think about the most efficient query strategy (Batch > Single).
    3. Output a numbered list of high-level actions (e.g., "1. Search for X", "2. Extract data", "3. Click Y").
    4. Keep it concise (max 5-7 steps).
    """

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Goal: {user_goal}\n\nProvide the step-by-step plan:"}
        ],
        "temperature": 0.6,
        "max_tokens": 1024,
        "stream": False
    }

    try:
        response = requests.post(PLANNER_API_URL, json=payload, timeout=60)
        if response.status_code == 200:
            result = response.json()
            plan_content = result['choices'][0]['message']['content']
            print("📋 [Planner] 初始計畫生成完畢！")
            return plan_content
        else:
            print(f"❌ [Planner Error] API 回傳錯誤: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ [Planner Error] 連線失敗: {e}")
        return None

def replan_task(user_goal: str, old_plan: str, current_status: str) -> str:
    """
    [Recovery Planner]
    當 Executor 卡關或陷入死循環時呼叫，重新擬定策略。
    """
    print(f"🧠 [Planner] 收到重規劃請求 (Re-planning)...")
    
    system_prompt = """
    You are an expert Web Automation Planner. 
    The executing agent is STUCK. 
    Your goal is to analyze the failure and generate a NEW, corrective plan.
    
    **Instructions:**
    1. Look at the User Goal and the Old Plan.
    2. Look at the Current Status (where it got stuck).
    3. Propose a workaround or a different approach.
    4. Output ONLY the new numbered step-by-step plan.

    **Optimization Tips for Recovery:**
    - If the previous plan involved multiple small steps that failed (e.g. searching year by year), switch to a **Batch Query** strategy.
    - Example: Instead of "Search 2020", "Search 2021", plan to "Search 'Canada population 2020 to 2023'".
    - This reduces steps and prevents memory loss.
    """

    user_content = f"""
    [User Goal]: {user_goal}
    [Old Plan]: {old_plan}
    [Current Status/Failure Log]: 
    {current_status}
    
    Please provide a NEW, recovered step-by-step plan:
    """

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7, # 稍微增加創造力以尋找新路徑
        "max_tokens": 1024,
        "stream": False
    }

    try:
        response = requests.post(PLANNER_API_URL, json=payload, timeout=60)
        if response.status_code == 200:
            result = response.json()
            new_plan = result['choices'][0]['message']['content']
            print(f"🚑 [Planner] 救援計畫已生成！")
            return new_plan
        else:
            print(f"❌ [Planner Re-plan Error]: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ [Planner Re-plan Exception]: {e}")
        return None

# 測試用
if __name__ == "__main__":
    goal = "Calculate the population growth rate of Canada from 2020 to 2023."
    print("--- Test Initial Plan ---")
    print(generate_plan(goal))
    
    print("\n--- Test Re-plan ---")
    status = "Stuck on Step 2. Searched for 2020, but page refreshed and I lost the data. Tried searching 2021 but got stuck."
    print(replan_task(goal, "Old Plan...", status))