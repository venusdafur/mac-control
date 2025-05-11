# 💻 Mac-Control

A Python-based Telegram bot designed for remote monitoring and control of a macOS system. This bot allows you to interact with your Mac, perform various actions, and receive updates directly through Telegram commands.

**Disclaimer:** This tool has powerful capabilities, including screen recording, webcam access, and keylogging. It is intended for legitimate use cases such as personal device monitoring, security auditing, or ethical hacking (with explicit permission). **Using this software for unauthorized access or malicious activities is illegal and unethical.** The developer is not responsible for any misuse. Please ensure you have the necessary permissions and adhere to all applicable laws and regulations.

## ✨ Features

This Telegram bot offers the following functionalities:

* **System Interaction:**
    * `/popup "<text>"`: Show a custom popup message on the macOS screen.
    * `/lock`: Remotely lock the macOS screen.
    * `/lockdown [seconds]`: Initiate a recurring screen lock, useful for security or as a prank. Can be set for a specific duration or indefinitely.
    * `/cancellockdown`: Stop the ongoing screen lockdown.
* **Visual Monitoring:**
    * `/ss`: Capture and send a screenshot of the current desktop.
    * `/screenrecord <seconds>`: Record the macOS screen for a specified duration (e.g., `/screenrecord 30` for 30 seconds) and send the video.
    * `/photo`: Take a photo using the built-in webcam and send it.
    * `/video <seconds>`: Record a video using the built-in webcam for a specified duration (e.g., `/video 15` for 15 seconds) and send it.
* **Input Monitoring (Keylogger):**
    * `/startkeylogger`: Begin logging keystrokes. Logs are periodically sent to the authorized chat.
    * `/stopkeylogger`: Stop the keylogger and send any remaining buffered keystrokes.
* **Network Monitoring:**
    * `/test`: Perform an internet connectivity test (ping to 1.1.1.1).
    * **Automated Wi-Fi & Internet Monitoring:** The bot includes background processes to monitor Wi-Fi power state and internet connectivity, sending alerts if changes are detected.
* **Basic Commands:**
    * `/start`: Get a welcome message and your authorized chat ID.
    * `/help`: Display a list of all available commands.

## 🛠️ Requirements

* **Operating System:** macOS
* **Python:** Python 3.x
* **Telegram Bot Token:** Obtain one from BotFather on Telegram.
* **External Command-Line Tools:**
    * `imagesnap`: For webcam photo capture. Install via Homebrew: `brew install imagesnap`
    * `ffmpeg`: For webcam video recording and screen recording video conversion. Install via Homebrew: `brew install ffmpeg`
    * `screencapture`: (Usually pre-installed on macOS, located at `/usr/sbin/screencapture`) Used for screenshots and screen recording.
    * `networksetup`: (Usually pre-installed on macOS) Used for Wi-Fi status checks.
    * `ping`: (Usually pre-installed on macOS) Used for internet connectivity tests.
* **Python Libraries:**
    * `pyTelegramBotAPI`: `pip3 install pyTelegramBotAPI`
    * `pynput`: For keylogging functionality. `pip3 install pynput --user` (The `--user` flag is often necessary to install it in your user directory due to system permissions.)

## ⚙️ Setup & Installation

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/venusdafur/mac-control.git](https://github.com/venusdafur/mac-control.git)
    cd mac-control
    ```

2.  **Install Dependencies:**
    ```bash
    pip3 install pyTelegramBotAPI
    pip3 install pynput --user
    brew install imagesnap ffmpeg # If not already installed
    ```
3.  **Configure the Bot:**
    * Open the `main.py` (or whatever your main script is named) file.
    * Replace `"your_token_here"` with your actual Telegram Bot Token:
        ```python
        BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
        ```
    * Replace `your_id_here` with your Telegram Chat ID. You can get this by messaging your new bot and then sending `/start`. Look for your ID in the bot's response:
        ```python
        AUTHORIZED_CHAT_ID = YOUR_TELEGRAM_CHAT_ID_HERE
        ```
    * Verify the paths for `imagesnap` and `ffmpeg`. If you installed them via Homebrew, the default paths `/opt/homebrew/bin/imagesnap` and `/opt/homebrew/bin/ffmpeg` should be correct for Apple Silicon Macs. For Intel Macs, they might be in `/usr/local/bin`. Adjust if necessary.

4.  **Grant macOS Permissions:**
    For the bot to function correctly, you **MUST** grant the `Python` interpreter (or `Terminal.app` if you run it directly from there) the necessary permissions in **System Settings > Privacy & Security**:
    * **Camera:** For `/photo` and `/video`.
    * **Screen Recording:** For `/screenrecord`.
    * **Accessibility:** For `/startkeylogger` (allows `pynput` to monitor keyboard input).

5.  **Run the Bot:**
    ```bash
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.your_name_here.telegramcontrol.plist
    ```

6. **File System:**
   Place *com.your_name_here.telegramcontrol.plist* in *~/Library/LaunchAgents/com.your_name_here.telegramcontrol.plist*.

   Place *telegram_control_bot.py* in *~/scripts/telegram_control_bot.py*.
    
## 🚀 Usage

Once the bot is running and you've granted permissions, you can send commands directly to your Telegram bot from your authorized chat. Refer to the `/help` command for a list of available actions.

**If you have any issues or it appears to not work > check the issues tab in github, if your answer isnt there then please file an issue report**
