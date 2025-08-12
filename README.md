# ADB & Scrcpy Runner

ADB & Scrcpy Runner is a graphical user interface (GUI) tool written in Python using Tkinter and ttkbootstrap. It simplifies running ADB (Android Debug Bridge) Shell and Scrcpy commands on connected Android devices. It provides a user-friendly way to manage and execute common commands, eliminating the need to type them manually in a terminal.

## Features

*   **Device Detection:** Automatically detects connected Android devices and displays their UDID, Android version, and model.
*   **Scrcpy Integration:**
    *   Automatically checks for a local Scrcpy installation.
    *   If not found, it offers to download the latest version for Windows automatically.
    *   Manages and executes Scrcpy commands in a dedicated tab.
*   **Command Management:**
    *   Loads ADB and Scrcpy commands from customizable text files (`useful_adb_commands.txt` and `useful_scrcpy_commands.txt`).
    *   Allows adding new commands through the GUI.
    *   Allows deleting existing commands through the GUI.
    *   Provides a "Refresh List" button to update the command list after manual file modifications.
*   **Command Execution:** Executes selected commands on the chosen device and displays the output directly in the application.
*   **Modern GUI:** Provides an intuitive graphical interface built with ttkbootstrap for a modern look and feel.

## Installation

### Prerequisites

*   **Python:** Ensure you have Python 3.7 or higher installed (if running from source).
*   **ADB:** ADB (Android Debug Bridge) must be installed and configured on your system. You can get it with the Android SDK Platform Tools. Make sure the `adb` executable is in your system's PATH.

### Installing from Executable (Windows)

1.  Go to the [Releases](https://github.com/lucasdeeiroz/adb_runner/releases) tab of this GitHub repository.
2.  Download the latest `adb_runner.exe` file.
3.  Place the executable file in a directory of your choice.
4.  Run the `adb_runner.exe` file. The application is portable.

### Installing from Source

1.  Clone this repository to your local machine:

    ```bash
    git clone https://github.com/lucasdeeiroz/adb_runner.git
    cd adb_runner
    ```

2.  Install the required Python packages:

    ```bash
    # Create and activate a virtual environment (optional but recommended)
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    # source venv/bin/activate

    # Install dependencies
    pip install -r requirements.txt
    ```

    (Create a `requirements.txt` file with the following content):

    ```txt
    ttkbootstrap
    ```

3.  Run the script:

    ```bash
    python adb_runner.py
    ```

## Usage

1.  **Connect your Android device:** Ensure your Android device is connected to your computer via USB and that USB debugging is enabled in the developer options.
2.  **Run the application:** Launch the `adb_runner.exe` or run the `adb_runner.py` script.
3.  **Download Scrcpy (if needed):** If you don't have Scrcpy, the app will prompt you to download it. This is required for the Scrcpy features.
4.  **Select a device:** Choose your device from the "Target Device" dropdown menu. If your device is not listed, click the "Refresh" button.
5.  **Navigate Tabs:** Use the "ADB Commands" and "Scrcpy Commands" tabs to switch between command types.
6.  **Select a command:** Choose a command from the list in the selected tab.
7.  **Execute the command:** Click the "Execute Command" button. The output (for ADB commands) will be displayed in the text area on the right. Scrcpy commands will open in a new window.
8.  **Manage Commands:**
    *   **Add:** Click "Add" to open a dialog and save a new command to the corresponding file.
    *   **Delete:** Click "Delete" to delete the command on the corresponding file.

## Configuration

The ADB Shell commands are loaded from the `useful_adb_commands.txt` file. Each line in the file represents a command. The format for each command is:

```
TITLE: <command_name>; ADB_COMMAND: <adb_command>
```

*   `<command_name>` is a descriptive name for the command (e.g., "Reboot Device").
*   `<adb_command>` is the actual ADB command to be executed (e.g., `reboot`).

The Scrcpy commands are loaded from the `useful_scrcpy_commands.txt` file. Each line in the file represents a command. The format for each command is:

```
TITLE: <command_name>; SCRCPY_COMMAND: <scrcpy_command>
```

*   `<command_name>` is a descriptive name for the command (e.g., "Mirror Device").
*   `<scrcpy_command>` is the actual scrcpy command to be executed (e.g., `reboot`).
