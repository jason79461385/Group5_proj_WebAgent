# config.py
# 存放所有 API 端點、金鑰和常數
import os
# --- (GPT-OSS) 設定 ---
GPT_OSS_SERVER_IP = "yourserver.ip"
GPT_OSS_MODEL_NAME = "GPT-OSS:120B"
GPT_OSS_SERVER_PORT = 11434
GPT_OSS_URL = f"http://{GPT_OSS_SERVER_IP}:{GPT_OSS_SERVER_PORT}/api/generate"

# --- (OpenAI) 設定 [新增] ---
USE_OPENAI_API = False # 預設關閉，由 main.py 控制
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "") # 請在環境變數或此處填入
OPENAI_MODEL_NAME = "gpt-4o" # 建議使用 gpt-4o 或 gpt-4-turbo

# --- (Embedding / RAG) 設定 ---
EMBEDDING_SERVER_URL = "http://yourserver.ip:11434"
EMBEDDING_MODEL_NAME = "bge-large:latest"
CHROMA_DB_PATH = "./chroma_memory_db"

# --- (OmniParser & UI-TARS) 設定 ---
OMNIPARSER_API_URL = "http://yourserver.ip:port/process_image"
UI_TARS_API_URL = "http://yourserver.ip:port/v1/chat/completions"

# --- 瀏覽器設定 ---
DEBUG_PORT = 9222
CHROME_PROFILE_NAME = "ChromeDebugProfile"