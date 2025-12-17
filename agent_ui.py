# agent_ui.py
# [Updated] V18 - URL Interceptor & Priority Logic Fix

import sys
import time
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QTextEdit, QScrollArea, QHBoxLayout, QMenu)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect
from PyQt6.QtGui import QPainter, QColor, QBrush, QAction, QGuiApplication

from agent_core import AgentCore # <--- 引入核心
import browser_controller

# --- 樣式表 (保持不變) ---
STYLESHEET = """
    QWidget { background-color: #2b2d30; color: #bbbbbb; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
    QLabel#TitleLabel { color: #ffffff; font-size: 16px; font-weight: bold; }
    QLineEdit { background-color: #3c3f41; border: 1px solid #5e6060; border-radius: 6px; color: #ffffff; padding: 8px 10px; }
    QTextEdit { background-color: #1e1f22; border: 1px solid #323232; border-radius: 6px; color: #a9b7c6; font-family: 'Consolas', monospace; font-size: 13px; }
    QPushButton { border-radius: 6px; padding: 8px 16px; font-weight: bold; border: none; }
    QPushButton:disabled { background-color: #404040; color: #707070; }
    QPushButton#MiniBtn { background-color: transparent; color: #808080; border: 1px solid #4a4a4a; font-size: 12px; }
    QPushButton#MiniBtn:hover { background-color: #3c3f41; color: white; }
    QPushButton#StartBtn { background-color: #365880; color: white; }
    QPushButton#StopBtn { background-color: #8c3b3b; color: white; }
    QPushButton#PauseBtn { background-color: #d19a66; color: #2b2d30; }
    QPushButton#ResumeBtn { background-color: #98c379; color: #2b2d30; }
"""

# --- 懸浮球 (保持不變) ---
class MiniFloatingWidget(QWidget):
    restore_signal = pyqtSignal()
    quit_signal = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.init_position()
        self.is_running = False
        self.drag_pos = None
    def init_position(self):
        screen = QGuiApplication.primaryScreen()
        if screen: self.setGeometry(screen.availableGeometry().width() - 80, 100, 60, 60)
        else: self.setGeometry(100, 100, 60, 60)
    def set_status(self, is_running):
        self.is_running = is_running
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(255, 87, 34) if self.is_running else QColor(76, 175, 80)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(5, 5, 50, 50)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        text = "BUSY" if self.is_running else "Agent"
        painter.drawText(QRect(0, 0, 60, 60), Qt.AlignmentFlag.AlignCenter, text)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.restore_signal.emit()
    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #2b2d30; color: white; } QMenu::item:selected { background-color: #4b6eaf; }")
        restore = QAction("展開主視窗", self)
        restore.triggered.connect(self.restore_signal.emit)
        quit_act = QAction("結束程式", self)
        quit_act.triggered.connect(self.quit_signal.emit)
        menu.addAction(restore)
        menu.addSeparator()
        menu.addAction(quit_act)
        menu.exec(pos)

# --- Agent Worker (現在只負責調度 Core) ---
class AgentWorker(QThread):
    log_signal = pyqtSignal(str)
    finish_signal = pyqtSignal()
    ui_state_signal = pyqtSignal(bool)
    pause_state_signal = pyqtSignal(bool)

    def __init__(self, driver, user_goal):
        super().__init__()
        # 初始化核心
        self.core = AgentCore(driver) 
        self.user_goal = user_goal
        self.is_running = True

    def stop(self):
        self.is_running = False
        self.log_signal.emit(">> 正在停止任務...")

    def pause(self):
        self.core.is_paused = True
        self.log_signal.emit("⏸️ 任務已暫停 (等待使用者操作...)")
        self.pause_state_signal.emit(True)

    def resume(self):
        self.core.is_paused = False
        self.log_signal.emit("▶️ 恢復執行任務...")
        self.pause_state_signal.emit(False)

    def run(self):
        self.ui_state_signal.emit(False)
        
        # 1. 任務重置 (Task Isolation)
        self.core.start_new_task(self.user_goal)
        
        max_steps = 20
        step_count = 0
        
        try:
            while step_count < max_steps and self.is_running:
                
                # --- PAUSE Logic (委託 Core 檢查) ---
                if self.core.is_paused:
                    try: paused_url = self.core.driver.current_url
                    except: paused_url = ""
                    while self.core.is_paused and self.is_running:
                        time.sleep(1)
                        if paused_url and self.core.check_login_status(paused_url):
                            self.log_signal.emit("⚡ 偵測到頁面跳轉，自動恢復！")
                            self.resume()
                            break
                    if not self.is_running: break
                    continue
                # -----------------------------------

                step_count += 1
                state = browser_controller.get_page_state(self.core.driver)
                self.log_signal.emit(f"\n[Step {step_count}] {state['title'][:20]}...")

                # 2. 大腦思考
                brain_command = self.core.analyze_next_step()
                
                if not self.is_running: break
                if not brain_command:
                    self.log_signal.emit("Error: 大腦無回應")
                    break

                intent = brain_command.get("intent", "interaction")
                thought = brain_command.get("thought", "")
                action = brain_command.get("action")
                is_finished = brain_command.get("is_finished", False) or (action == "finish")
                target = brain_command.get("target_description")
                value = brain_command.get("value")
                auto_submit = brain_command.get("submit", False)

                self.log_signal.emit(f"Think: {thought}")
                self.log_signal.emit(f"Intent: {intent}")

                # === [Critical Fix] URL 攔截器 (Priority Interceptor) ===
                # 只要 value 是網址，強制覆蓋任何 intent，優先執行跳轉
                # 這避免了 LLM 誤將網址丟給 global_search
                if value and isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
                    self.log_signal.emit(f"🚀 偵測到 URL 輸入，強制轉換為 goto_url 動作: {value}")
                    # 改寫 Action 為 goto_url
                    brain_command["action"] = "goto_url"
                    brain_command["value"] = value      
                    # [Fix] 整包傳入，讓 Core 處理 Log 和 History
                    result_dict = self.core.execute_action(brain_command)

                    # 手動提取 success 和 message，並給予預設值以防萬一
                    success = result_dict.get("success", False)
                    msg = result_dict.get("message", "Unknown Action Result")
                    continue
                # ========================================================

                # 3. 意圖處理
                if intent == "request_help":
                    self.log_signal.emit("🆘 Agent 請求支援：遇到無法處理的狀況。")
                    self.pause()
                    continue

                if is_finished:
                    self.log_signal.emit("🔍 任務回報完成，開始驗證...")
                    verified, reason = self.core.verify_completion()
                    if verified:
                        self.log_signal.emit(f"✅ {reason}")
                        self.log_signal.emit("Done: 任務完成")
                        final_answer = brain_command.get('value', '')
                        if not final_answer:
                            final_answer = str(self.core.scratchpad)
                        self.log_signal.emit(f"🏁 最終答案: {final_answer}")
                        break
                    else:
                        self.log_signal.emit(f"❌ {reason}")
                        self.log_signal.emit("🔄 繼續嘗試...")
                        continue

                # 3. 處理全網搜尋 (只有在不是 URL 的情況下才會執行到這)
                if intent == "global_search":
                    # 雙重保險：如果 value 是空或奇怪的東西，擋下來
                    if not value:
                        self.log_signal.emit("⚠️ 搜尋關鍵字為空，跳過。")
                        continue
                        
                    search_url = f"https://www.google.com/search?q={value}"
                    self.log_signal.emit(f"Global Search: {value}")
                    self.core.driver.get(search_url)
                    browser_controller.wait_for_page_load(self.core.driver)
                    self.core.history.append(f"Global Search for '{value}'")
                    continue

                # 4. 執行動作 (呼叫 Core)
                result_dict = self.core.execute_action(brain_command)

                    # 手動提取 success 和 message，並給予預設值以防萬一
                success = result_dict.get("success", False)
                msg = result_dict.get("message", "Unknown Action Result")
                if not success:
                    self.log_signal.emit(f"Warning: {msg}")
                
        except Exception as e:
            self.log_signal.emit(f"Error: {e}")
            import traceback
            traceback.print_exc()

        self.log_signal.emit("--- 任務結束 ---")
        self.ui_state_signal.emit(True)
        self.finish_signal.emit()

# --- UI Controller (保持不變) ---
class AgentController(QWidget):
    # ... (請保留原本 UI Controller 的所有代碼，完全不用動) ...
    # 為了節省篇幅，這裡假設 AgentController 代碼與上一版相同
    # 只需確保它在 start_task 中實例化的是新的 AgentWorker
    def __init__(self, agent_driver):
        super().__init__()
        self.agent_driver = agent_driver
        self.worker = None
        self.mini_widget = MiniFloatingWidget()
        self.mini_widget.restore_signal.connect(self.restore_window)
        self.mini_widget.quit_signal.connect(self.close_application)
        self.setStyleSheet(STYLESHEET)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Pro Agent Controller")
        self.resize(550, 600)
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15) 
        top_layout = QHBoxLayout()
        self.title_label = QLabel("Autonomous Agent")
        self.title_label.setObjectName("TitleLabel")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        self.mini_btn = QPushButton("懸浮模式")
        self.mini_btn.setObjectName("MiniBtn")
        self.mini_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini_btn.clicked.connect(self.switch_to_mini_mode)
        top_layout.addWidget(self.mini_btn)
        layout.addLayout(top_layout)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("系統準備就緒...")
        layout.addWidget(self.log_area)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("輸入指令...")
        self.entry.returnPressed.connect(self.start_task)
        layout.addWidget(self.entry)
        btn_layout = QHBoxLayout()
        self.start_button = QPushButton("開始執行")
        self.start_button.setObjectName("StartBtn")
        self.start_button.clicked.connect(self.start_task)
        btn_layout.addWidget(self.start_button)
        self.pause_button = QPushButton("暫停 (II)")
        self.pause_button.setObjectName("PauseBtn")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        btn_layout.addWidget(self.pause_button)
        self.stop_button = QPushButton("強制停止")
        self.stop_button.setObjectName("StopBtn")
        self.stop_button.clicked.connect(self.stop_task)
        self.stop_button.setEnabled(False)
        btn_layout.addWidget(self.stop_button)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        if self.agent_driver: self.log("[System] Ready")

    def log(self, message):
        self.log_area.append(message)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def update_ui_state(self, is_idle):
        self.entry.setEnabled(is_idle)
        self.start_button.setEnabled(is_idle)
        self.stop_button.setEnabled(not is_idle)
        self.mini_widget.set_status(is_running=(not is_idle))
        if is_idle:
            self.start_button.setText("開始執行")
            self.pause_button.setEnabled(False)
            self.pause_button.setText("暫停 (II)")
        else:
            self.start_button.setText("執行中...")
            self.pause_button.setEnabled(True)

    def update_pause_state(self, is_paused):
        if is_paused:
            self.pause_button.setText("恢復執行 (▶)")
            self.pause_button.setObjectName("ResumeBtn")
            self.pause_button.setStyleSheet("background-color: #98c379; color: #2b2d30;") 
        else:
            self.pause_button.setText("暫停 (II)")
            self.pause_button.setObjectName("PauseBtn")
            self.pause_button.setStyleSheet("background-color: #d19a66; color: #2b2d30;")

    def closeEvent(self, event):
        event.ignore()
        self.switch_to_mini_mode()

    def switch_to_mini_mode(self):
        self.hide(); self.mini_widget.show(); self.mini_widget.raise_(); self.mini_widget.activateWindow()

    def restore_window(self):
        self.mini_widget.hide(); self.show(); self.raise_(); self.activateWindow()

    def close_application(self):
        if self.worker and self.worker.isRunning(): self.worker.stop(); self.worker.wait()
        if self.agent_driver: 
            try: self.agent_driver.quit() 
            except: pass
        QApplication.quit()

    def start_task(self):
        goal = self.entry.text()
        if not goal: return
        self.worker = AgentWorker(self.agent_driver, goal)
        self.worker.log_signal.connect(self.log)
        self.worker.ui_state_signal.connect(self.update_ui_state)
        self.worker.pause_state_signal.connect(self.update_pause_state)
        self.worker.start()

    def stop_task(self):
        if self.worker: self.worker.stop()

    def toggle_pause(self):
        if self.worker:
            if self.worker.core.is_paused: self.worker.resume()
            else: self.worker.pause()