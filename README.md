python version: `3.11.12`

Make sure undetected_chromedriver's version is the same as your chrome's version.

Use pyenv or conda to create same python version's enviroment

then we use venv to install what we need

To install packages: `pip install -r requirements.txt`  

# How to run this
`python main.py`

```
📦 Project_Root
 ┣ 📜 agent_core.py ...... [CORE] The central orchestrator. Manages the main perception-decision-action loop, including the Reflex System (popup killer), Visual-DOM alignment, and state tracking.
 ┣ 📜 api_clients.py ..... [INTERFACE] Handles all API calls to LLMs (DeepSeek, GPT-OSS) and VLMs (UI-TARS, OmniParser). Includes robust JSON parsing and strict output enforcement.
 ┣ 📜 browser_controller.py .. [HANDS] Low-level browser interactions using Selenium/Undetected-Chromedriver. Handles clicking, scrolling, typing, and JS injection for stealth.
 ┣ 📜 memory_manager.py ... [MEMORY] Manages Long-term Memory (RAG) using ChromaDB. Retrieving past successful paths and storing new insights.
 ┣ 📜 planner_client.py ... [STRATEGIST] Interface for the Planner (DeepSeek-R1). Generates high-level strategic plans and handles re-planning when the agent gets stuck.
 ┣ 📜 human_mouse.py ..... [STEALTH] Implements human-like mouse movements using Bezier curves to bypass bot detection.
 ┗ 📜 utils.py .... [HELPER] Utility functions for image processing (SoM tagging), coordinate conversion (HiDPI fix), and history sanitization.
 ┃
 ┣ 📜 main.py ......... [ENTRY] The standard entry point to launch the agent for a single task.
 ┣ 📜 agent_ui.py ......[FRONTEND] A graphical user interface (likely Gradio/Streamlit) for users to interact with the agent visually.
 ┗ 📜 init_knowledge.py ...... [SETUP] Scripts to initialize the RAG database with seed data or clear previous memory.
 ┃
 ┣ 📜 test_suite.py ...... [TEST] The main testing engine. Runs the agent against the dataset (Singleton Driver Mode) and records pass/fail status.
 ┣ 📜 test_logger.py ......... [LOGGING] Logs detailed execution steps, thoughts, and errors for debugging and analysis.
 ┣ 📜 analyze_logs.py ........ [ANALYSIS] Scripts to parse generated logs and calculate success rates or error distributions.
 ┣ 📜 test_dataset.json ...... [DATA] The full benchmark dataset (e.g., WebVoyager tasks).
 ┗ 📜 test_dataset_50.json ... [DATA] A sampled subset (e.g., 50 tasks) used for rapid experimentation.
 ┣ 📜 config.py .............. [SETTINGS] Global configuration file (API keys, model endpoints, browser settings, timeouts).
 ┗ 📜 requirements.txt ....... [DEPENDENCIES] List of Python libraries required to run the project.
```
[![Watch the video](https://img.youtube.com/vi/FwnJ_RSyNBU/maxresdefault.jpg)](https://youtu.be/FwnJ_RSyNBU)
