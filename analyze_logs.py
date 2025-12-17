# analyze_logs.py
import os
import json
import glob

def analyze_latest_session():
    # 1. 找到最新的 Log 資料夾
    log_root = "test_logs"
    if not os.path.exists(log_root):
        print("沒有 Log 資料。")
        return

    sessions = sorted(os.listdir(log_root))
    if not sessions: return
    
    latest_session = os.path.join(log_root, sessions[-1])
    print(f"📂 分析 Log 資料夾: {latest_session}\n")

    # 2. 讀取所有 JSON
    json_files = glob.glob(os.path.join(latest_session, "*.json"))
    
    failed_cases = []
    
    for jf in json_files:
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data['status'] == "FAIL":
                failed_cases.append(data)

    # 3. 輸出分析報告
    print(f"🔴 總計失敗: {len(failed_cases)} 筆\n")
    
    for case in failed_cases:
        print("="*60)
        print(f"🆔 Case ID: {case['id']}")
        print(f"🎯 Goal: {case['goal']}")
        print(f"❌ Error: {case['error_msg']}")
        
        # 顯示最後一步的思考 (通常是死因)
        if case['steps']:
            last_step = case['steps'][-1]
            print("-" * 20)
            print(f"🧠 [Last Thought (Step {last_step['step']})]")
            print(f"Planner: {last_step.get('planner_thought', 'N/A')}")
            print(f"Executor: {last_step.get('executor_thought', 'N/A')}")
            print(f"Action: {last_step.get('action')} -> Target: {last_step.get('target')}")
        else:
            print("⚠️ No steps recorded.")
        print("\n")

if __name__ == "__main__":
    analyze_latest_session()