# main.py
import sys
import argparse
import config
from PyQt6.QtWidgets import QApplication
from browser_controller import initialize_agent
from agent_ui import AgentController
from init_knowledge import sync_system_knowledge

def parse_arguments():
    parser = argparse.ArgumentParser(description="Pro Agent Runner")
    parser.add_argument("--use_GPT_KEY", action="store_true", help="Use OpenAI API instead of Local LLM")
    parser.add_argument("--key", type=str, help="OpenAI API Key (optional if set in env/config)", default="")
    return parser.parse_args()

if __name__ == "__main__":
    # 1. 處理參數
    args = parse_arguments()
    
    if args.use_GPT_KEY:
        print("🚀 [Mode] 切換至 OpenAI 模式")
        config.USE_OPENAI_API = True
        if args.key:
            config.OPENAI_API_KEY = args.key
        
        if not config.OPENAI_API_KEY:
            print("❌ 錯誤: 啟用 OpenAI 模式但未提供 Key。")
            print("請使用 --key 'sk-...' 或在 config.py 設定。")
            sys.exit(1)
    else:
        print("🏠 [Mode] 使用本地 GPT-OSS 模式")

    # 2. 同步知識庫
    sync_system_knowledge()

    # 3. 初始化瀏覽器
    driver_instance = initialize_agent()
    if not driver_instance:
        sys.exit(1)
    
    # 4. 啟動 UI
    app = QApplication(sys.argv)
    controller_ui = AgentController(agent_driver=driver_instance)
    controller_ui.show()
    
    sys.exit(app.exec())