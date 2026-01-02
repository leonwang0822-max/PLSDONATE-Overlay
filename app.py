import asyncio
import json
import logging
import sys
import os
import threading
import traceback
import time
from datetime import datetime

VERSION = "v1.0.0"
GITHUB_REPO = "leonwang0822-max/PLSDONATE-Overlay"

# Global Exception Hook to catch crashes and keep window open
def exception_hook(exctype, value, tb):
    print("CRITICAL ERROR OCCURRED:")
    print("".join(traceback.format_exception(exctype, value, tb)))
    input("Press Enter to exit...")
    sys.exit(1)

sys.excepthook = exception_hook

try:
    import pyperclip
except ImportError:
    print("Warning: pyperclip not found. Clipboard features will be disabled.")
    pyperclip = None

from quart import Quart, render_template, websocket, request, jsonify
import websockets
from chat_manager import ChatManager

# Try to import PyQt6 for GUI
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit, QProgressBar, QMessageBox
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtCore import QUrl, QTimer, pyqtSignal, QObject
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# Determine paths for PyInstaller
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Quart(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Quart(__name__)

# Configuration
if getattr(sys, 'frozen', False):
    # If running as EXE, save config to AppData to be persistent
    app_data = os.path.join(os.environ.get('APPDATA'), 'PLS_DONATE_Overlay')
    if not os.path.exists(app_data):
        os.makedirs(app_data)
    config_file = os.path.join(app_data, "config.json")
else:
    # If running from source, save to current directory
    config_file = "config.json"

config = {
    "user_id": None,
    "min_amount": 0,
    "chat_template": "Thanks for the {amount}R$ donation by @{username}",
    "twitch_enabled": False,
    "twitch_token": "",
    "twitch_channel": "",
    "youtube_enabled": False,
    "youtube_token": "",
    "youtube_chat_id": ""
}

# Load config
try:
    with open(config_file, "r") as f:
        saved_config = json.load(f)
        config.update(saved_config)
except FileNotFoundError:
    pass

# State
connected_clients = set()
BASE_WS = "wss://stream.plsdonate.com/api/user/{}/websocket"
donation_history = []  # Store session history
chat_manager = ChatManager()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Silence annoying google cache warning
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

def save_config():
    with open(config_file, "w") as f:
        json.dump(config, f)

async def broadcast(message):
    for client in connected_clients:
        try:
            await client.send(json.dumps(message))
        except Exception:
            pass

async def plsdonate_listener():
    current_user_id = None
    
    while True:
        target_user_id = config.get("user_id")
        
        if not target_user_id:
            await asyncio.sleep(1)
            continue
            
        url = BASE_WS.format(target_user_id)
        logger.info(f"Connecting to {url}...")
        
        try:
            # Add ping_interval to keep connection alive (every 10s)
            async with websockets.connect(url, ping_interval=10, ping_timeout=10) as ws:
                logger.info(f"Connected to stream for user {target_user_id}")
                current_user_id = target_user_id
                
                async for msg in ws:
                    # If user ID changed, break to reconnect
                    if config.get("user_id") != current_user_id:
                        logger.info("User ID changed, reconnecting...")
                        break
                        
                    try:
                        data = json.loads(msg)
                        if "ping_interval" in data:
                             # It's a ping message, ignore
                             continue
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Process donation
                        if "sender" in data and "amount" in data:
                            sender_name = data["sender"].get("displayName", "Unknown")
                            sender_user = data["sender"].get("username", "Unknown")
                            amount = data.get("amount", 0)
                            message = data.get("message", "")
                            
                            event = {
                                "type": "donation",
                                "timestamp": timestamp,
                                "sender_name": sender_name,
                                "sender_user": sender_user,
                                "amount": amount,
                                "message": message,
                                "raw": data
                            }
                            
                            # Add to history
                            donation_history.append(event)
                            # Keep history reasonable
                            if len(donation_history) > 100:
                                donation_history.pop(0)
                                
                            logger.info(f"Donation: {sender_name} - {amount}")
                            await broadcast(event)
                            
                            # Send chat message if amount meets threshold
                            if amount >= config.get("min_amount", 0):
                                await chat_manager.send_message(event)
                        else:
                            # Forward other events if needed
                            pass
                            
                    except json.JSONDecodeError:
                        logger.error(f"Received non-JSON message: {msg}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        
        except Exception as e:
            logger.error(f"Connection error: {e}")
            await asyncio.sleep(5) # Wait before retry

@app.before_serving
async def startup():
    await chat_manager.update_config(config)
    # Use app.add_background_task is not reliable for long running task in some Quart versions/servers
    # Create a proper asyncio task
    asyncio.create_task(plsdonate_listener())

@app.route("/")
async def index():
    return await render_template("index.html", config=config)

@app.route("/leaderboard")
async def leaderboard():
    return await render_template("leaderboard.html")

@app.route("/api/settings", methods=["POST"])
async def update_settings():
    data = await request.get_json()
    
    # Update config with all known keys
    for key in config.keys():
        if key in data:
            if key == "min_amount":
                config[key] = int(data[key])
            else:
                config[key] = data[key]
    
    save_config() # Save to file
    await chat_manager.update_config(config)
    
    return jsonify({"status": "ok", "config": config})

@app.route("/api/history")
async def get_history():
    return jsonify(donation_history)

@app.route("/api/copy_to_clipboard", methods=["POST"])
async def copy_to_clipboard():
    if not pyperclip:
        return jsonify({"status": "error", "message": "Clipboard module not available"}), 500
        
    data = await request.get_json()
    text = data.get("text", "")
    try:
        pyperclip.copy(text)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Clipboard copy failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.websocket("/ws")
async def ws():
    connected_clients.add(websocket._get_current_object())
    try:
        while True:
            await websocket.receive() # Keep connection open
    except asyncio.CancelledError:
        connected_clients.remove(websocket._get_current_object())
    except Exception:
        connected_clients.remove(websocket._get_current_object())

if __name__ == "__main__":
    PORT = 5000
    HOST = "127.0.0.1"
    URL = f"http://{HOST}:{PORT}"

    def run_server():
        try:
            # Run Hypercorn directly to avoid signal handler issues in background thread
            from hypercorn.config import Config
            from hypercorn.asyncio import serve
            
            config = Config()
            config.bind = [f"{HOST}:{PORT}"]
            config.use_reloader = False
            
            # Create a new loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Custom shutdown trigger to prevent Hypercorn from registering signal handlers
            shutdown_event = asyncio.Event()
            
            # Run the server
            loop.run_until_complete(serve(app, config, shutdown_trigger=shutdown_event.wait))
        except Exception as e:
            logger.error(f"Server error: {e}")

    if GUI_AVAILABLE:
        # Custom WebEnginePage to open links in system browser
        class CustomWebEnginePage(QWebEnginePage):
            def acceptNavigationRequest(self, url,  _type, isMainFrame):
                url_str = url.toString()
                logger.info(f"Navigation Request: {url_str} (Type: {_type})")
                
                # Check if it's an external link (not our local server)
                host = url.host()
                if host and host != "127.0.0.1" and host != "localhost":
                    logger.info(f"External link detected: {url_str}")
                    QDesktopServices.openUrl(url)
                    return False
                
                # Also handle explicit link clicks just in case
                if _type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                    logger.info(f"Link Click detected: {url_str}")
                    QDesktopServices.openUrl(url)
                    return False
                    
                return super().acceptNavigationRequest(url, _type, isMainFrame)

            def createWindow(self, _type):
                # Handle target="_blank" clicks
                # We return a new dummy page to handle the navigation request off-screen.
                # This prevents the main window from navigating away or becoming blank.
                # The dummy page will trigger its own acceptNavigationRequest, 
                # which opens the system browser and returns False.
                # QWebEnginePage expects a QObject parent (optional) or QWebEngineProfile
                # Here we pass None as parent to avoid type errors, but we need to keep a reference
                # so it doesn't get garbage collected immediately.
                new_page = CustomWebEnginePage(parent=None)
                # Keep a reference to prevent garbage collection
                if not hasattr(self, '_extra_pages'):
                    self._extra_pages = []
                self._extra_pages.append(new_page)
                return new_page

        # Define Log Signals/Handler for GUI
        class LogSignal(QObject):
            write = pyqtSignal(str)
            
        class GuiLogHandler(logging.Handler):
            def __init__(self, sig):
                super().__init__()
                self.sig = sig
                
            def emit(self, record):
                msg = self.format(record)
                self.sig.write.emit(msg)

        # Start GUI First
        try:
            qt_app = QApplication(sys.argv)
            qt_app.setApplicationName("PLS DONATE Overlay Manager")
            
            window = QMainWindow()
            window.setWindowTitle("PLS DONATE Overlay Manager")
            window.resize(1024, 800)
            
            # Setup Loading Screen
            loading_widget = QWidget()
            layout = QVBoxLayout()
            
            title_label = QLabel("Starting PLS DONATE Overlay...")
            title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin: 20px; color: #ffffff;")
            layout.addWidget(title_label)
            
            # Progress Bar
            progress_bar = QProgressBar()
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    background-color: #2b2b2b;
                    color: white;
                }
                QProgressBar::chunk {
                    background-color: #007acc;
                    width: 20px;
                }
            """)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            layout.addWidget(progress_bar)
            
            log_view = QTextEdit()
            log_view.setReadOnly(True)
            log_view.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px; padding: 10px;")
            layout.addWidget(log_view)
            
            loading_widget.setLayout(layout)
            window.setCentralWidget(loading_widget)
            window.show()
            
            # Connect Logging
            log_signal = LogSignal()
            log_signal.write.connect(log_view.append)
            gui_handler = GuiLogHandler(log_signal)
            gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logging.getLogger().addHandler(gui_handler)
            logger.info("Initializing application...")

            # Start server in background thread
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            
            # Non-blocking Check for Server
            import urllib.request
            
            start_time = time.time()
            
            def check_connection():
                elapsed = time.time() - start_time
                # Update progress (0-90% based on time, last 10% on success)
                progress = min(int((elapsed / 3.0) * 90), 90)
                progress_bar.setValue(progress)
                
                if elapsed < 3:
                    return # Wait at least 3 seconds

                try:
                    urllib.request.urlopen(URL, timeout=0.2)
                    # Server is ready!
                    progress_bar.setValue(100)
                    logger.info("Server is ready! Loading dashboard...")
                    timer.stop()
                    
                    # Switch to Browser
                    browser = QWebEngineView()
                    page = CustomWebEnginePage(browser)
                    browser.setPage(page)
                    browser.setUrl(QUrl(URL))
                    window.setCentralWidget(browser)
                    
                    # Cleanup logger
                    logging.getLogger().removeHandler(gui_handler)
                    
                    # Check for updates in background
                    threading.Thread(target=check_for_updates, args=(window,), daemon=True).start()
                except Exception:
                    pass # Keep waiting
            
            def check_for_updates(parent_window):
                try:
                    import requests
                    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        latest_version = data.get("tag_name", "").strip()
                        if latest_version and latest_version != VERSION:
                            # Use QMetaObject.invokeMethod to run on main thread
                            from PyQt6.QtCore import QMetaObject, Q_ARG, Qt
                            
                            def show_dialog():
                                msg = QMessageBox(parent_window)
                                msg.setWindowTitle("Update Available")
                                msg.setText(f"A new version {latest_version} is available!")
                                msg.setInformativeText("Would you like to download it now?")
                                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                msg.setDefaultButton(QMessageBox.StandardButton.Yes)
                                if msg.exec() == QMessageBox.StandardButton.Yes:
                                    QDesktopServices.openUrl(QUrl(data.get("html_url")))
                            
                            # We need to run this on the main thread.
                            # Since we are in a thread, we can't create widgets directly.
                            # A simple way is to use a signal, but we don't have a class here.
                            # We can define a SignalObject.
                            
                            # Let's reuse the existing LogSignal concept or create a new one.
                            update_signal.show_update.emit(latest_version, data.get("html_url"))

                except Exception as e:
                    logger.error(f"Update check failed: {e}")

            # Define Signal for Update
            class UpdateSignal(QObject):
                show_update = pyqtSignal(str, str)
            
            update_signal = UpdateSignal()
            def on_show_update(version, url):
                msg = QMessageBox(window)
                msg.setWindowTitle("Update Available")
                msg.setText(f"A new version {version} is available!")
                msg.setInformativeText("Would you like to download it now?")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setDefaultButton(QMessageBox.StandardButton.Yes)
                if msg.exec() == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(url))
            
            update_signal.show_update.connect(on_show_update)

            timer = QTimer()
            timer.timeout.connect(check_connection)
            timer.start(100) # Check more frequently for smooth progress bar
            
            sys.exit(qt_app.exec())
        except Exception as e:
            logger.exception("GUI crashed")
            input("Press Enter to exit...")
    else:
        logger.warning("PyQt6 not found. Running in console mode.")
        try:
            import webbrowser
            threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
            app.run(host=HOST, port=PORT)
        except Exception:
            logger.exception("Program crashed")
            input("Press Enter to exit...")
        finally:
            input("Press Enter to exit...")
