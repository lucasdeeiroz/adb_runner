import tkinter as tk
from tkinter import messagebox, simpledialog
import ttkbootstrap as ttk
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.constants import *
import subprocess
import sys
import json
import urllib.request
import zipfile
import threading
from typing import List, Tuple, Dict, Optional
from pathlib import Path
import time
import datetime
from queue import Queue, Empty
import ctypes
import os
import signal

# --- Conditional import for pywin32 ---
if sys.platform == "win32":
    try:
        import win32gui
        import win32process
        import win32con
    except ImportError:
        messagebox.showerror(
            "Dependency Missing",
            "The 'pywin32' library is required for scrcpy embedding on Windows.\n"
            "Please install it by running: pip install pywin32"
        )
        sys.exit(1)


# --- Constants ---
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

ADB_COMMANDS_FILE = BASE_DIR / "useful_adb_commands.txt"
SCRCPY_COMMANDS_FILE = BASE_DIR / "useful_scrcpy_commands.txt"


# --- Console Redirector Class ---
class ConsoleRedirector:
    """A class to redirect stdout/stderr to a tkinter text widget."""
    def __init__(self, text_widget: ScrolledText):
        self.text_widget = text_widget
        self.text_widget.text.config(state=NORMAL)

    def write(self, text: str):
        """Writes text to the widget and scrolls to the end."""
        self.text_widget.insert(END, text)
        self.text_widget.see(END)

    def flush(self):
        """Flush method is required for stream-like objects."""
        pass

# --- Scrcpy Window Class ---
class ScrcpyEmbedWindow(tk.Toplevel):
    """A Toplevel window to display and embed a scrcpy instance."""
    def __init__(self, parent, command_template: str, udid: str, title: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("1200x800")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.command_template = command_template
        self.udid = udid
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self.original_style = None
        self.original_parent = None
        self.output_queue = Queue()
        self.aspect_ratio = None
        self.resize_job = None

        self.is_recording = False
        self.recording_process = None
        self.recording_device_path = ""
        self.output_is_visible = True
        self._is_closing = False

        self._setup_widgets()
        self._start_scrcpy()
        self.after(100, self._check_output_queue)
        self.bind("<Configure>", self._on_window_resize)

    def _setup_widgets(self):
        """Creates the layout for the scrcpy window."""
        main_frame = ttk.Frame(self, padding=5)
        main_frame.pack(fill=BOTH, expand=YES)
        
        self.main_paned_window = ttk.PanedWindow(main_frame, orient=HORIZONTAL)
        self.main_paned_window.pack(fill=BOTH, expand=YES)

        left_pane_container = ttk.Frame(self.main_paned_window)
        self.main_paned_window.add(left_pane_container, weight=1)

        self.left_paned_window = ttk.PanedWindow(left_pane_container, orient=VERTICAL)
        self.left_paned_window.pack(fill=BOTH, expand=YES)

        commands_frame = ttk.LabelFrame(self.left_paned_window, text="Scrcpy Commands", padding=10)
        self.left_paned_window.add(commands_frame, weight=1)

        self.output_frame = ttk.LabelFrame(self.left_paned_window, text="Scrcpy Output", padding=5)
        self.output_text = ScrolledText(self.output_frame, wrap=WORD, state=DISABLED, autohide=True)
        self.output_text.pack(fill=BOTH, expand=YES)
        self.left_paned_window.add(self.output_frame, weight=1)

        self.screenshot_button = ttk.Button(commands_frame, text="Take Screenshot", command=self._take_screenshot)
        self.screenshot_button.pack(fill=X, pady=5, padx=5)

        self.record_button = ttk.Button(commands_frame, text="Start Recording", command=self._toggle_recording, bootstyle="primary")
        self.record_button.pack(fill=X, pady=5, padx=5)

        self.toggle_output_button = ttk.Button(commands_frame, text="Hide Output", command=self._toggle_output_visibility, bootstyle="secondary")
        self.toggle_output_button.pack(fill=X, pady=5, padx=5)

        self.embed_frame = ttk.LabelFrame(self.main_paned_window, text="Screen Mirror", padding=5)
        self.main_paned_window.add(self.embed_frame, weight=3)
        
    def _start_scrcpy(self):
        """Starts the scrcpy process and management threads in the background."""
        thread = threading.Thread(target=self._run_and_embed_scrcpy)
        thread.daemon = True
        thread.start()

    def _run_and_embed_scrcpy(self):
        """Runs scrcpy, captures its output, and embeds its window."""
        try:
            self.unique_title = f"scrcpy_{int(time.time() * 1000)}"
            command_with_udid = self.command_template.format(udid=self.udid)
            command_to_run = f'{command_with_udid} --window-title="{self.unique_title}"'

            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            
            self.scrcpy_process = subprocess.Popen(
                command_to_run,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags
            )

            output_thread = threading.Thread(target=self._pipe_output_to_queue)
            output_thread.daemon = True
            output_thread.start()

            self._find_and_embed_window()

        except Exception as e:
            self.output_queue.put(f"FATAL ERROR: Failed to start scrcpy process.\n{e}\n")

    def _pipe_output_to_queue(self):
        """Reads output from the process line-by-line and puts it in a thread-safe queue."""
        if not self.scrcpy_process: return
        for line in iter(self.scrcpy_process.stdout.readline, ''):
            self.output_queue.put(line)
        self.scrcpy_process.stdout.close()

    def _check_output_queue(self):
        """Periodically checks the queue and updates the GUI text widget."""
        while not self.output_queue.empty():
            try:
                line = self.output_queue.get_nowait()
                self.output_text.text.config(state=NORMAL)
                self.output_text.insert(END, line)
                self.output_text.see(END)
                self.output_text.text.config(state=DISABLED)

                if "INFO: Texture:" in line and not self.aspect_ratio:
                    try:
                        resolution = line.split(":")[-1].strip()
                        width, height = map(int, resolution.split('x'))
                        if height > 0:
                            self.aspect_ratio = width / height
                            self.after(100, self._adjust_aspect_ratio)
                    except (ValueError, IndexError):
                        pass
            except Empty:
                pass
        self.after(100, self._check_output_queue)

    def _on_window_resize(self, event=None):
        """Callback for when the main Toplevel window is resized. Debounces events."""
        if self.aspect_ratio:
            if self.resize_job:
                self.after_cancel(self.resize_job)
            self.resize_job = self.after(100, self._adjust_aspect_ratio)

    def _adjust_aspect_ratio(self):
        """Adjusts the paned window sash to match the device's aspect ratio."""
        self.resize_job = None
        if not self.aspect_ratio:
            return

        self.update_idletasks()

        pane_height = self.embed_frame.winfo_height()
        if pane_height <= 1:
            self.after(100, self._adjust_aspect_ratio)
            return

        ideal_mirror_width = int(pane_height * self.aspect_ratio)
        total_width = self.main_paned_window.winfo_width()
        
        new_sash_pos = total_width - ideal_mirror_width

        min_output_width = 250
        if new_sash_pos < min_output_width:
            new_sash_pos = min_output_width
        if new_sash_pos > total_width - min_output_width:
             new_sash_pos = total_width - min_output_width

        try:
            self.main_paned_window.sashpos(0, new_sash_pos)
        except tk.TclError:
            pass

    def _find_and_embed_window(self):
        """Finds the scrcpy window by its unique title, then embeds it."""
        start_time = time.time()
        
        while time.time() - start_time < 15:
            hwnd = win32gui.FindWindow(None, self.unique_title)
            if hwnd:
                self.scrcpy_hwnd = hwnd
                self.after(0, self._embed_window)
                return
            time.sleep(0.2)
        
        self.output_queue.put(f"ERROR: Could not find scrcpy window with title '{self.unique_title}' in time.\n")

    def _embed_window(self):
        """Uses pywin32 to embed the found window into a Tkinter frame."""
        if not self.scrcpy_hwnd: return

        container_id = self.embed_frame.winfo_id()
        self.original_parent = win32gui.SetParent(self.scrcpy_hwnd, container_id)
        
        self.original_style = win32gui.GetWindowLong(self.scrcpy_hwnd, win32con.GWL_STYLE)
        new_style = self.original_style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(self.scrcpy_hwnd, win32con.GWL_STYLE, new_style)

        self.embed_frame.update_idletasks()
        width = self.embed_frame.winfo_width()
        height = self.embed_frame.winfo_height()
        win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, width, height, True)

        self.embed_frame.bind("<Configure>", self._resize_child)
        self.output_queue.put(f"INFO: Embedded scrcpy window (HWND: {self.scrcpy_hwnd})\n")

    def _resize_child(self, event):
        """Resizes the embedded scrcpy window when its container frame is resized."""
        if self.scrcpy_hwnd:
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, event.width, event.height, True)

    def _on_close(self):
        """Handles the window close event, ensuring processes are terminated safely."""
        if self._is_closing:
            return
        self._is_closing = True

        def final_close_actions():
            """Terminates scrcpy and destroys the window."""
            if self.scrcpy_process and self.scrcpy_process.poll() is None:
                self.output_queue.put("INFO: Terminating scrcpy process...\n")
                self.scrcpy_process.terminate()
                try:
                    self.scrcpy_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.scrcpy_process.kill()
            self.destroy()

        if self.is_recording:
            self.output_queue.put("INFO: Window closing, stopping active recording...\n")
            self.record_button.config(state=DISABLED)
            self.screenshot_button.config(state=DISABLED)

            def stop_and_close_thread():
                """Runs the blocking stop command then schedules the final close."""
                self._stop_recording_thread()
                self.master.after(0, final_close_actions)

            threading.Thread(target=stop_and_close_thread, daemon=True).start()
        else:
            final_close_actions()

    def _toggle_output_visibility(self):
        """Shows or hides the Scrcpy Output console."""
        if self.output_is_visible:
            self.left_paned_window.forget(self.output_frame)
            self.toggle_output_button.config(text="Show Output")
        else:
            self.left_paned_window.add(self.output_frame, weight=1)
            self.toggle_output_button.config(text="Hide Output")
        self.output_is_visible = not self.output_is_visible

    def _take_screenshot(self):
        """Takes a screenshot and saves it locally in a non-blocking thread."""
        self.screenshot_button.config(state=DISABLED)
        thread = threading.Thread(target=self._take_screenshot_thread)
        thread.daemon = True
        thread.start()

    def _take_screenshot_thread(self):
        """The actual logic for taking a screenshot."""
        self.output_queue.put("INFO: Taking screenshot...\n")
        
        screenshots_dir = BASE_DIR / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        device_filename = "/sdcard/screenshot.png"
        local_filename = f"screenshot_{self.udid.replace(':', '-')}_{timestamp}.png"
        local_filepath = screenshots_dir / local_filename

        try:
            capture_cmd = f"adb -s {self.udid} shell screencap -p {device_filename}"
            success_cap, out_cap = execute_command(capture_cmd)
            if not success_cap:
                self.output_queue.put(f"ERROR: Failed to capture screenshot.\n{out_cap}\n")
                return

            pull_cmd = f"adb -s {self.udid} pull {device_filename} \"{local_filepath}\""
            success_pull, out_pull = execute_command(pull_cmd)
            if not success_pull:
                self.output_queue.put(f"ERROR: Failed to pull screenshot.\n{out_pull}\n")
            else:
                self.output_queue.put(f"SUCCESS: Screenshot saved to {local_filepath}\n")

            rm_cmd = f"adb -s {self.udid} shell rm {device_filename}"
            execute_command(rm_cmd)
        finally:
            self.master.after(0, lambda: self.screenshot_button.config(state=NORMAL))

    def _toggle_recording(self):
        """Starts or stops the screen recording."""
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        """Starts a screen recording in a separate thread."""
        self.record_button.config(state=DISABLED)
        thread = threading.Thread(target=self._start_recording_thread)
        thread.daemon = True
        thread.start()

    def _start_recording_thread(self):
        """The actual logic for starting a recording."""
        recordings_dir = BASE_DIR / "recordings"
        recordings_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        device_filename = f"recording_{timestamp}.mp4"
        self.recording_device_path = f"/sdcard/{device_filename}"
        
        command_list = ["adb", "-s", self.udid, "shell", "screenrecord", self.recording_device_path]
        
        self.output_queue.put(f"INFO: Starting recording...\n> {' '.join(command_list)}\n")

        try:
            p_flags = 0
            if sys.platform == "win32":
                p_flags = subprocess.CREATE_NEW_PROCESS_GROUP

            self.recording_process = subprocess.Popen(
                command_list,
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True, 
                encoding='utf-8', 
                errors='replace',
                creationflags=p_flags
            )
            self.master.after(0, self._update_recording_ui, True)
        except Exception as e:
            self.output_queue.put(f"ERROR: Failed to start recording process.\n{e}\n")
            self.master.after(0, lambda: self.record_button.config(state=NORMAL))

    def _stop_recording(self):
        """Stops the screen recording in a separate thread."""
        self.record_button.config(state=DISABLED)
        thread = threading.Thread(target=self._stop_recording_thread)
        thread.daemon = True
        thread.start()

    def _stop_recording_thread(self):
        """The actual logic for stopping a recording and saving the file."""
        self.output_queue.put("INFO: Stopping recording...\n")

        if not self.recording_process or self.recording_process.poll() is not None:
            self.output_queue.put("ERROR: No active recording process found to stop.\n")
            self.master.after(0, self._update_recording_ui, False)
            return

        try:
            self.recording_process.kill()
            self.recording_process.wait(timeout=10)
            self.output_queue.put("INFO: Recording process stopped.\n")
            self.output_queue.put("INFO: Now trying to save the file...\n")

        except subprocess.TimeoutExpired:
            self.output_queue.put("WARNING: Recording process did not stop in time, killing it forcefully.\n")
            self.recording_process.kill()
        except Exception as e:
            self.output_queue.put(f"ERROR: An error occurred while stopping the recording: {e}\n")
            self.recording_process.kill()

        time.sleep(2)

        recordings_dir = BASE_DIR / "recordings"
        local_filename = Path(self.recording_device_path).name
        local_filepath = recordings_dir / f"{self.udid.replace(':', '-')}_{local_filename}"

        pull_cmd = f"adb -s {self.udid} pull {self.recording_device_path} \"{local_filepath}\""
        success_pull, out_pull = execute_command(pull_cmd)
        if not success_pull:
            self.output_queue.put(f"ERROR: Failed to pull recording.\n{out_pull}\n")
        else:
            self.output_queue.put(f"SUCCESS: Recording saved to {local_filepath}\n")

        rm_cmd = f"adb -s {self.udid} shell rm {self.recording_device_path}"
        execute_command(rm_cmd)

        self.master.after(0, self._update_recording_ui, False)

    def _update_recording_ui(self, is_recording: bool):
        """Helper to update UI elements from the main thread."""
        self.is_recording = is_recording
        if is_recording:
            self.record_button.config(text="Stop Recording", state=NORMAL, bootstyle="danger-outline")
        else:
            self.record_button.config(text="Start Recording", state=NORMAL, bootstyle="primary")
            self.recording_process = None
            self.recording_device_path = ""


# --- Core Logic Functions (Separated from GUI) ---

def manage_adb_server(start: bool = True):
    """
    Starts or kills the ADB server to ensure a single, managed instance.
    This prevents multiple adb.exe processes from being created and left running.
    """
    command = "adb start-server" if start else "adb kill-server"
    action = "Starting" if start else "Killing"
    print(f"INFO: {action} ADB server...")
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        stdout, stderr = process.communicate(timeout=10)
        if process.returncode != 0:
            print(f"WARNING: Command '{command}' may have failed.")
            error_output = (stdout.decode('utf-8', 'replace') + stderr.decode('utf-8', 'replace')).strip()
            if error_output:
                 print(f"Output:\n{error_output}")
        else:
            print(f"INFO: ADB server command '{command}' executed successfully.")

    except subprocess.TimeoutExpired:
        print(f"ERROR: Timeout expired for command '{command}'. Killing process.")
        process.kill()
    except Exception as e:
        print(f"ERROR: Failed to execute '{command}': {e}")

# SOLUTION: New function to manage scrcpy processes.
def manage_scrcpy_processes():
    """
    Kills any running scrcpy.exe processes to prevent duplicates and ensure cleanup.
    This is a Windows-specific solution using taskkill.
    """
    if sys.platform != "win32":
        return

    command = "taskkill /F /IM scrcpy.exe"
    print("INFO: Killing any lingering scrcpy.exe processes...")
    try:
        # We run this command to clean up. It's okay if it fails (e.g., if no processes are found).
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        process.communicate(timeout=10)
        print("INFO: Scrcpy cleanup command executed.")
    except subprocess.TimeoutExpired:
        print(f"ERROR: Timeout expired for scrcpy cleanup. Killing process.")
        process.kill()
    except Exception as e:
        # We log the error but don't bother the user, as this is a cleanup task.
        print(f"NOTE: Could not perform scrcpy cleanup: {e}")


def hide_console():
    """Hides the console window on Windows."""
    if sys.platform == "win32":
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window != 0:
            ctypes.windll.user32.ShowWindow(console_window, 0)

def execute_command(command: str) -> Tuple[bool, str]:
    """Executes a shell command and returns a tuple (success, output)."""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            output = stdout + stderr
            if "device not found" in output:
                return False, "Error: Device not found."
            if "* daemon not running" in output:
                return False, "ADB daemon is not responding. Please wait..."
            return False, f"Error executing command:\n{output.strip()}"

        return True, (stdout + stderr).strip()

    except FileNotFoundError:
        return False, "Error: Command or executable not found. Check your system's PATH."
    except Exception as e:
        return False, f"An unexpected error occurred: {e}"

def get_device_info(udid: str) -> Tuple[Optional[str], Optional[str]]:
    """Gets the Android version and model for a given device UDID."""
    version_cmd = f"adb -s {udid} shell getprop ro.build.version.release"
    model_cmd = f"adb -s {udid} shell getprop ro.product.model"
    success_ver, version = execute_command(version_cmd)
    success_mod, model = execute_command(model_cmd)
    return (version if success_ver else "N/A", model if success_mod else "N/A")

def get_connected_devices() -> List[Tuple[str, str, str]]:
    """Gets a list of connected devices with their UDID, version, and model."""
    devices = []
    success, output = execute_command("adb devices")
    if not success or not output:
        return []
    lines = output.strip().splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            udid = parts[0]
            version, model = get_device_info(udid)
            devices.append((udid, version, model))
    return devices

def load_commands_from_file(filepath: Path, scrcpy_path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    """Loads commands from a text file, creating it if it doesn't exist."""
    if not filepath.exists():
        create_default_command_file(filepath)
    
    commands = {}
    try:
        with open(filepath, "r", encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                
                parts = line.split(";", 1)
                if len(parts) < 2 or not parts[0].upper().startswith("TITLE:"):
                    continue

                title = parts[0][len("TITLE:"):].strip()
                cmd_part = parts[1].strip()

                if "ADB_COMMAND:" in cmd_part.upper():
                    command = cmd_part[len("ADB_COMMAND:"):].strip()
                    full_command = f"adb -s {{udid}} shell {command}"
                    commands[title] = {"command": full_command, "type": "ADB"}
                elif "SCRCPY_COMMAND:" in cmd_part.upper() and scrcpy_path:
                    command = cmd_part[len("SCRCPY_COMMAND:"):].strip()
                    full_command = f'"{scrcpy_path / "scrcpy.exe"}" -s {{udid}} {command}'
                    commands[title] = {"command": full_command, "type": "SCRCPY"}
    except IOError as e:
        messagebox.showerror("File Error", f"Could not read file {filepath}: {e}")
    return commands

def save_commands_to_file(filepath: Path, command: Dict[str, Dict[str, str]]):
    """Saves the provided commands dictionary back to the file."""
    command_type = command['type']
    raw_command = command["command"]
    command_title = command["title"]

    if command_type == "SCRCPY":
        f_command = raw_command.split('scrcpy.exe ', 1)[-1].strip()
    if command_type == "ADB":
        f_command = raw_command.split('shell ', 1)[-1].strip()
    try:
        with open(filepath, "a", encoding='utf-8') as f:
            f.write(f"\nTITLE: {command_title} ; {command_type}_COMMAND: {f_command}")
    except IOError as e:
        messagebox.showerror("File Error", f"Could not save commands to {filepath}: {e}")

def create_default_command_file(filepath: Path):
    """Creates a default command file."""
    try:
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(f"// {filepath.name}")
            f.write("\n// Add your commands here. Format: TITLE: My Title ; COMMAND_TYPE: command")
            f.write("\n// Lines starting with // are ignored.")
            if filepath == ADB_COMMANDS_FILE:
                f.write("\n// Use 'adb shell' commands, but leave out that part of the command.")
                f.write("\nTITLE: Get Android version ; ADB_COMMAND: getprop ro.build.version.release")
                f.write("\nTITLE: Get device model ; ADB_COMMAND: getprop ro.product.model")
            elif filepath == SCRCPY_COMMANDS_FILE:
                f.write("\n// Use 'scrcpy' commands, but leave the executable out of the command.")
                f.write("\n// The --window-title argument is added automatically by the application.")
                f.write("\nTITLE: Mirror screen (default) ; SCRCPY_COMMAND:")
                f.write("\nTITLE: Mirror as virtual display (1920x1080) ; SCRCPY_COMMAND: --new-display=1920x1080/284")
    except IOError as e:
        messagebox.showerror("File Error", f"Could not create default file {filepath}: {e}")

def check_and_download_scrcpy() -> Optional[Path]:
    """Checks for a local scrcpy folder, otherwise offers to download it."""
    for folder in BASE_DIR.glob("scrcpy-win64-*"):
        if folder.is_dir() and (folder / "scrcpy.exe").exists():
            return folder

    if not messagebox.askyesno("Scrcpy Not Found", "Scrcpy was not found. Do you want to download the latest version automatically?"):
        return None

    try:
        url = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
        
        asset_url = next((asset["browser_download_url"] for asset in data.get("assets", []) if asset["name"].startswith("scrcpy-win64-")), None)
        
        if not asset_url:
            messagebox.showerror("Download Error", "Could not find the download asset for Windows 64-bit.")
            return None

        zip_path = BASE_DIR / "scrcpy.zip"
        urllib.request.urlretrieve(asset_url, zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)
        
        zip_path.unlink()
        return next((folder for folder in BASE_DIR.glob("scrcpy-win64-*") if folder.is_dir()), None)

    except Exception as e:
        messagebox.showerror("Download Error", f"Failed to download or extract Scrcpy: {e}")
        return None

# --- Main Application Class ---
class AdbRunnerApp:
    def __init__(self, root: ttk.Window):
        self.root = root
        self.root.title("ADB & Scrcpy Runner")
        self.root.geometry("900x750")

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.scrcpy_path = check_and_download_scrcpy()
        self.commands: Dict[Path, Dict[str, str]] = {}

        self._create_widgets()
        self._redirect_console()

        # SOLUTION: Start the ADB server and kill any old scrcpy processes on launch.
        threading.Thread(target=manage_adb_server, args=(True,), daemon=True).start()
        threading.Thread(target=manage_scrcpy_processes, daemon=True).start()

        self._initial_refresh()

    # SOLUTION: Updated method to handle application closing gracefully for both ADB and Scrcpy.
    def _on_closing(self):
        """Handles cleanup before the application window is destroyed."""
        print("INFO: Close button clicked. Shutting down ADB server and scrcpy processes...")
        # Kill the ADB server and any running scrcpy instances in the background.
        threading.Thread(target=manage_adb_server, args=(False,), daemon=True).start()
        threading.Thread(target=manage_scrcpy_processes, daemon=True).start()
        # Give the commands a moment to dispatch before destroying the window.
        self.root.after(300, self.root.destroy)

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=BOTH, expand=YES)

        device_frame = ttk.LabelFrame(main_frame, text="Target Device", padding=10)
        device_frame.pack(fill=X, pady=(0, 10))

        self.device_combobox = ttk.Combobox(device_frame, state="readonly", font=("Segoe UI", 10))
        self.device_combobox.pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))

        self.refresh_button = ttk.Button(device_frame, text="Refresh", command=self._refresh_devices, bootstyle="secondary")
        self.refresh_button.pack(side=LEFT)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=BOTH, expand=YES)

        self.adb_listbox, self.adb_output_text = self._create_command_tab(notebook, "ADB Commands", ADB_COMMANDS_FILE)
        
        if self.scrcpy_path:
            self.scrcpy_listbox, self.scrcpy_output_text = self._create_command_tab(notebook, "Scrcpy Commands", SCRCPY_COMMANDS_FILE)
        else:
            scrcpy_tab = ttk.Frame(notebook, padding=20)
            notebook.add(scrcpy_tab, text="Scrcpy Commands (Unavailable)")
            ttk.Label(scrcpy_tab, text="Scrcpy not found. Restart the app to try downloading again.").pack()
            notebook.tab(1, state="disabled")

        self._create_connect_tab(notebook)
        
        self._create_about_tab(notebook)

    def _redirect_console(self):
        """Redirects stdout and stderr to the console widget."""
        console_redirector = ConsoleRedirector(self.console_output_text)
        sys.stdout = console_redirector
        sys.stderr = console_redirector

    def _create_command_tab(self, parent: ttk.Notebook, title: str, cmd_file: Path) -> Tuple[tk.Listbox, ScrolledText]:
        tab_frame = ttk.Frame(parent, padding=10)
        parent.add(tab_frame, text=title)
        
        tab_frame.rowconfigure(0, weight=1) 
        tab_frame.rowconfigure(1, weight=0) 
        tab_frame.columnconfigure(0, weight=1)

        paned_window = ttk.PanedWindow(tab_frame, orient=HORIZONTAL)
        paned_window.grid(row=0, column=0, sticky="nsew")

        list_frame = ttk.Frame(paned_window)
        listbox = tk.Listbox(list_frame, height=10, font=("Segoe UI", 10), relief=FLAT, borderwidth=5)
        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL, command=listbox.yview, bootstyle="round")
        listbox['yscrollcommand'] = scrollbar.set
        
        scrollbar.pack(side=RIGHT, fill=Y)
        listbox.pack(side=LEFT, fill=BOTH, expand=YES)
        paned_window.add(list_frame, weight=1)

        output_frame = ttk.Frame(paned_window)
        output_text = ScrolledText(output_frame, wrap=WORD, state=DISABLED, relief=FLAT, borderwidth=5, autohide=True, bootstyle="round")
        output_text.pack(fill=BOTH, expand=YES)
        paned_window.add(output_frame, weight=2)

        actions_frame = ttk.Frame(tab_frame)
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        
        ttk.Button(actions_frame, text="Add", command=lambda: self._add_command(cmd_file, listbox), bootstyle="success-outline").pack(side=LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="Delete", command=lambda: self._delete_command(cmd_file, listbox), bootstyle="danger-outline").pack(side=LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="Refresh List", command=lambda: self._refresh_command_list(cmd_file, listbox), bootstyle="info-outline").pack(side=LEFT)
        
        self.execute_button = ttk.Button(actions_frame, text="Execute Command", command=lambda: self._execute_gui_command(listbox, output_text, cmd_file), bootstyle="primary")
        self.execute_button.pack(side=RIGHT)

        return listbox, output_text

    def _create_connect_tab(self, parent: ttk.Notebook):
        """Creates the 'Connect' tab for wireless debugging."""
        connect_tab = ttk.Frame(parent, padding=20)
        parent.add(connect_tab, text="Connect")

        pair_frame = ttk.LabelFrame(connect_tab, text="Pair Device", padding=15)
        pair_frame.pack(fill=X, pady=(0, 20))

        ttk.Label(pair_frame, text="IP Address:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.pair_ip_entry = ttk.Entry(pair_frame, width=30)
        self.pair_ip_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(pair_frame, text="Port:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.pair_port_entry = ttk.Entry(pair_frame, width=10)
        self.pair_port_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(pair_frame, text="Pairing Code:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.pair_code_entry = ttk.Entry(pair_frame, width=10)
        self.pair_code_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        self.pair_button = ttk.Button(pair_frame, text="Pair", command=self._pair_device, bootstyle="primary")
        self.pair_button.grid(row=3, column=1, padx=5, pady=10, sticky="e")
        pair_frame.columnconfigure(1, weight=1)

        connect_frame = ttk.LabelFrame(connect_tab, text="Connect Device", padding=15)
        connect_frame.pack(fill=X, pady=(0, 20))

        ttk.Label(connect_frame, text="IP Address:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.connect_ip_entry = ttk.Entry(connect_frame, width=30)
        self.connect_ip_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(connect_frame, text="Port:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.connect_port_entry = ttk.Entry(connect_frame, width=10)
        self.connect_port_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        self.disconnect_button = ttk.Button(connect_frame, text="Disconnect", command=self._disconnect_device, bootstyle="danger-outline")
        self.disconnect_button.grid(row=2, column=0, padx=5, pady=10, sticky="e")
        self.connect_button = ttk.Button(connect_frame, text="Connect", command=self._connect_device, bootstyle="primary")
        self.connect_button.grid(row=2, column=1, padx=5, pady=10, sticky="e")
        connect_frame.columnconfigure(1, weight=1)

        output_frame = ttk.LabelFrame(connect_tab, text="Output", padding=10)
        output_frame.pack(fill=BOTH, expand=YES)
        self.connect_output_text = ScrolledText(output_frame, wrap=WORD, state=DISABLED, autohide=True)
        self.connect_output_text.pack(fill=BOTH, expand=YES)

    def _pair_device(self):
        """Handles the logic for pairing a device."""
        ip = self.pair_ip_entry.get().strip()
        port = self.pair_port_entry.get().strip()
        code = self.pair_code_entry.get().strip()

        if not all([ip, port, code]):
            messagebox.showwarning("Input Required", "Please fill in all fields for pairing.")
            return

        command = f"adb pair {ip}:{port}"
        self._update_output_text(self.connect_output_text, f"Attempting to pair with {ip}:{port}...\n", clear=True)
        self.pair_button.config(state=DISABLED)

        thread = threading.Thread(target=self._run_pair_command_thread, args=(command, code, self.connect_output_text))
        thread.daemon = True
        thread.start()

    def _run_pair_command_thread(self, command: str, code: str, output_widget: ScrolledText):
        """Executes the pairing command in a separate thread."""
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            stdout, stderr = process.communicate(input=f"{code}\n")
            
            output = stdout + stderr
            self.root.after(0, self._update_output_text, output_widget, f"Result:\n{output.strip()}", False)

        except Exception as e:
            self.root.after(0, self._update_output_text, output_widget, f"An unexpected error occurred: {e}", False)
        
        finally:
            self.root.after(0, lambda: self.pair_button.config(state=NORMAL))
            self.root.after(100, self._refresh_devices)


    def _connect_device(self):
        """Handles the logic for connecting to a device."""
        ip = self.connect_ip_entry.get().strip()
        port = self.connect_port_entry.get().strip()

        if not all([ip, port]):
            messagebox.showwarning("Input Required", "Please fill in IP Address and Port to connect.")
            return
        
        command = f"adb connect {ip}:{port}"
        self._update_output_text(self.connect_output_text, f"Attempting to connect to {ip}:{port}...\n", clear=True)
        self.connect_button.config(state=DISABLED)

        thread = threading.Thread(target=self._run_command_and_update_gui, args=(command, self.connect_output_text, self.connect_button, True))
        thread.daemon = True
        thread.start()

    def _disconnect_device(self):
        """Handles the logic for connecting to a device."""
        ip = self.connect_ip_entry.get().strip()
        port = self.connect_port_entry.get().strip()

        if not ip and port:
            messagebox.showwarning("Input Required", "Please fill in IP Address to disconnect.")
            return
        elif not port and ip:
            messagebox.showwarning("Input Required", "Please fill in Port to disconnect.")
            return
        elif not all([ip, port]):
            command = "adb disconnect"
        else:
            command = f"adb disconnect {ip}:{port}"
        self._update_output_text(self.connect_output_text, f"Attempting to disconnect...\n", clear=True)
        self.disconnect_button.config(state=DISABLED)

        thread = threading.Thread(target=self._run_command_and_update_gui, args=(command, self.connect_output_text, self.disconnect_button, True))
        thread.daemon = True
        thread.start()

    def _create_about_tab(self, parent: ttk.Notebook):
        """Creates the 'About' tab with project info and credits."""
        about_tab = ttk.Frame(parent, padding=20)
        parent.add(about_tab, text="About")

        ttk.Label(about_tab, text="ADB & Scrcpy Runner", font=("Segoe UI", 18, "bold")).pack(pady=(0, 10))
        description = ("This application provides a graphical user interface for executing common "
                       "Android Debug Bridge (ADB) and Scrcpy commands on connected devices.")
        ttk.Label(about_tab, text=description, wraplength=600, justify=CENTER).pack(pady=(0, 25))

        credits_frame = ttk.LabelFrame(about_tab, text="Acknowledgements", padding=15)
        credits_frame.pack(fill=X, pady=(0, 10))

        credits_text = {
            "Android Debug Bridge (ADB):": "Developed by Google as part of the Android SDK.",
            "Scrcpy:": "An incredible screen mirroring application by Genymobile.",
            "ttkbootstrap:": "A modern theme extension for Tkinter by Israel Dryer.",
            "pywin32:": "Python for Windows Extensions by Mark Hammond."
        }

        for tool, credit in credits_text.items():
            credit_line = ttk.Frame(credits_frame)
            credit_line.pack(fill=X, pady=2)
            ttk.Label(credit_line, text=tool, font=("Segoe UI", 10, "bold")).pack(side=LEFT)
            ttk.Label(credit_line, text=f" {credit}").pack(side=LEFT)
        
        license_frame = ttk.LabelFrame(about_tab, text="License", padding=15)
        license_frame.pack(fill=BOTH, expand=YES, pady=(10, 0))

        license_text_widget = ScrolledText(license_frame, wrap=WORD, height=10, autohide=True)
        license_text_widget.pack(fill=BOTH, expand=YES)
        
        license_content = """MIT License

Copyright (c) 2024 Lucas de Eiroz Rodrigues

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
        
        license_text_widget.insert(END, license_content)
        license_text_widget.text.config(state=DISABLED)
        
        console_frame = ttk.LabelFrame(about_tab, text="Console Output", padding=10)
        console_frame.pack(fill=X, pady=(0, 10))
        self.console_output_text = ScrolledText(console_frame, height=1, wrap=WORD, state=DISABLED, relief=FLAT, borderwidth=5, autohide=True, bootstyle="round")
        self.console_output_text.pack(fill=BOTH, expand=YES)
            
    def _initial_refresh(self):
        self._refresh_devices()
        self._refresh_command_list(ADB_COMMANDS_FILE, self.adb_listbox)
        if self.scrcpy_path:
            self._refresh_command_list(SCRCPY_COMMANDS_FILE, self.scrcpy_listbox)
            self._update_output_text(self.scrcpy_output_text, f"Scrcpy found at: {self.scrcpy_path}\n", clear=True)

    def _refresh_devices(self):
        self.device_combobox['values'] = []
        self.device_combobox.set("Searching for devices...")
        self.refresh_button.config(state=DISABLED)
        
        thread = threading.Thread(target=self._get_devices_thread)
        thread.daemon = True
        thread.start()

    def _get_devices_thread(self):
        devices = get_connected_devices()
        self.root.after(0, self._update_device_list, devices)
        if devices:
            self.root.after(0, self._update_output_text(self.adb_output_text, f"Devices found:\n", clear=True))
            for device in devices:
                self._update_output_text(self.adb_output_text, f"\n{device[2]} (Android {device[1]}) - UDID: {device[0]}", clear=False)
        else:
            self._update_output_text(self.adb_output_text, "No devices found.", clear=False)
        self._update_output_text(self.adb_output_text, "\n----------------------", clear=False)


    def _update_device_list(self, devices: List[Tuple[str, str, str]]):
        if devices:
            device_strings = [f"{model} ({udid})" for udid, _, model in devices]
            self.device_combobox['values'] = device_strings
            self.device_combobox.set(device_strings[0])
        else:
            self.device_combobox.set("No devices found")
        self.refresh_button.config(state=NORMAL)

    def _refresh_command_list(self, cmd_file: Path, listbox: tk.Listbox):
        listbox.delete(0, tk.END)
        self.commands[cmd_file] = load_commands_from_file(cmd_file, self.scrcpy_path)
        for title in sorted(self.commands[cmd_file].keys()):
            listbox.insert(END, title)

    def _execute_gui_command(self, listbox: tk.Listbox, output_text: ScrolledText, cmd_file: Path):
        if not listbox.curselection():
            messagebox.showwarning("No Selection", "Please select a command to execute.")
            return
        selected_title = listbox.get(listbox.curselection())
        
        selected_device = self.device_combobox.get()
        if not selected_device or "No devices" in selected_device:
            messagebox.showwarning("No Device", "Please select a target device.")
            return
        
        udid = selected_device.split('(')[-1].replace(')', '')
        cmd_data = self.commands[cmd_file].get(selected_title)
        if not cmd_data: return

        command_template = cmd_data['command']
        
        if cmd_data.get('type') == 'SCRCPY':
            if sys.platform != "win32":
                messagebox.showerror("Unsupported OS", "Scrcpy embedding is only supported on Windows.")
                return
            ScrcpyEmbedWindow(self.root, command_template, udid, f"Scrcpy - {selected_title}")
        else:
            final_command = command_template.format(udid=udid)
            self._update_output_text(output_text, f"Executing: {final_command}\n\n", clear=True)
            self.execute_button.config(state=DISABLED)
            thread = threading.Thread(target=self._run_command_and_update_gui, args=(final_command, output_text, self.execute_button, False))
            thread.daemon = True
            thread.start()

    def _run_command_and_update_gui(self, command: str, output_widget: ScrolledText, button: ttk.Button, refresh_on_success: bool = False):
        success, output = execute_command(command)
        if not output:
            self.root.after(0, self._update_output_text, output_widget, f"Result: {success}", False)
        else:
            self.root.after(0, self._update_output_text, output_widget, f"Result: {output}", False)
        
        if success and refresh_on_success:
            self.root.after(100, self._refresh_devices)
            
        self.root.after(0, lambda: button.config(state=NORMAL))


    def _update_output_text(self, widget: ScrolledText, result: str, clear: bool):
        widget.text.config(state=NORMAL)
        if clear:
            widget.delete("1.0", END)
        widget.insert(END, result)
        widget.text.config(state=DISABLED)
        widget.see(END)
        
    def _add_command(self, cmd_file: Path, listbox: tk.Listbox):
        title = simpledialog.askstring("Add Command", "\nEnter a title for the new command:\n", parent=self.root)
        if not title: return

        command_type = "ADB" if cmd_file == ADB_COMMANDS_FILE else "SCRCPY"
        prompt = f"\nEnter the {command_type} command arguments (the part after 'adb shell' or 'scrcpy.exe'):\n"
        raw_command = simpledialog.askstring("Add Command", prompt, parent=self.root)
        if not raw_command: return

        new_command = {"title": title, "type": command_type, "command": raw_command}
        save_commands_to_file(cmd_file, new_command)
        self._refresh_command_list(cmd_file, listbox)

    def _delete_command(self, cmd_file: Path, listbox: tk.Listbox):
        if not listbox.curselection():
            messagebox.showwarning("No Selection", "Please select a command to delete.")
            return
        selected_title = listbox.get(listbox.curselection())

        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete '{selected_title}'?"):
            try:
                with open(cmd_file, "r", encoding='utf-8') as f_read:
                    lines = f_read.readlines()
                
                with open(cmd_file, "w", encoding='utf-8') as f_write:
                    for line in lines:
                        if f"TITLE: {selected_title} ;" not in line:
                            f_write.write(line)
                
                self._refresh_command_list(cmd_file, listbox)
                messagebox.showinfo("Command Deleted", f"Command '{selected_title}' deleted successfully.")
            except IOError as e:
                messagebox.showerror("File Error", f"Could not modify file {cmd_file}: {e}")

if __name__ == "__main__":
    hide_console()
    root = ttk.Window(themename="darkly")
    app = AdbRunnerApp(root)
    root.mainloop()
