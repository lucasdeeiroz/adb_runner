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
import ctypes

# --- Constants ---
ADB_COMMANDS_FILE = Path("useful_adb_commands.txt")
SCRCPY_COMMANDS_FILE = Path("useful_scrcpy_commands.txt")
BASE_DIR = Path(__file__).resolve().parent

# --- Core Logic Functions (Separated from GUI) ---

def hide_console():
    """Hides the console window on Windows when running as a frozen executable."""
    if sys.platform == "win32":
        if getattr(sys, 'frozen', False):
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

def execute_command(command: str) -> Tuple[bool, str]:
    """Executes a shell command and returns a tuple (success, output)."""
    try:
        if "scrcpy.exe" in command:
            subprocess.Popen(f'start cmd /K "{command}"', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return True, "Scrcpy started in a new window."
        else:
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
                if "device not found" in stderr:
                    return False, "Error: Device not found."
                if "* daemon not running" in stderr:
                    return False, "ADB daemon is not responding. Please wait..."
                return False, f"Error executing command:\n{stderr.strip()}"

            return True, stdout.strip()

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
    # Strip the scrcpy path for saving to keep it portable
    # This is a bit complex; we need to extract the user-defined part
    # For simplicity, we assume the command format is consistent.
    # A more robust solution might store the raw command separately.
    if command_type == "SCRCPY":
        f_command = raw_command.split('scrcpy.exe ', 1)[-1].strip()
    if command_type == "ADB":
        f_command = raw_command.split('shell ', 1)[-1].strip()
    try:
        # Open in append mode ('a') to add to the end of the file
        # Add a newline character before writing to ensure it's on a new line
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
                f.write("\n// Use 'scrcpy' commands, but leave tthe executable out of the command.")
                f.write("\nTITLE: Mirror screen (default) ; SCRCPY_COMMAND: --window-title=\"Mirror of {udid}\"")
                f.write("\nTITLE: Mirror as virtual display (1920x1080) ; SCRCPY_COMMAND: --new-display=1920x1080/284 --window-title=\"Virtual Display of {udid}\"")
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
        self.root.geometry("900x600")

        self.scrcpy_path = check_and_download_scrcpy()
        self.commands: Dict[Path, Dict[str, Dict[str, str]]] = {}

        self._create_widgets()
        self._initial_refresh()

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

    def _create_command_tab(self, parent: ttk.Notebook, title: str, cmd_file: Path) -> Tuple[tk.Listbox, ScrolledText]:
        tab_frame = ttk.Frame(parent, padding=10)
        parent.add(tab_frame, text=title)

        paned_window = ttk.PanedWindow(tab_frame, orient=HORIZONTAL)
        paned_window.pack(fill=BOTH, expand=YES)

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
        actions_frame.pack(fill=X, pady=(10, 0))
        
        ttk.Button(actions_frame, text="Add", command=lambda: self._add_command(cmd_file, listbox), bootstyle="success-outline").pack(side=LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="Delete", command=lambda: self._delete_command(cmd_file, listbox), bootstyle="danger-outline").pack(side=LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="Refresh List", command=lambda: self._refresh_command_list(cmd_file, listbox), bootstyle="info-outline").pack(side=LEFT)
        
        self.execute_button = ttk.Button(actions_frame, text="Execute Command", command=lambda: self._execute_gui_command(listbox, output_text, cmd_file), bootstyle="primary")
        self.execute_button.pack(side=RIGHT)

        return listbox, output_text

    def _initial_refresh(self):
        self._refresh_devices()
        self._refresh_command_list(ADB_COMMANDS_FILE, self.adb_listbox)
        if self.scrcpy_path:
            self._refresh_command_list(SCRCPY_COMMANDS_FILE, self.scrcpy_listbox)
            self._update_output_text(self.scrcpy_output_text, f"\nScrcpy found at: {self.scrcpy_path}\n", clear=False)

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
        self.root.after(0, self._update_output_text(self.adb_output_text, f"\nDevices found:\n", clear=True))
        for device in devices:
            self.root.after(0, self._update_output_text(self.adb_output_text, f"\nModel: {device[2]} - Android {device[1]} - UDID: {device[0]}", clear=False))

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
        
        command_str = cmd_data['command'].format(udid=udid)
        
        self._update_output_text(output_text, f"Executing: {command_str}\n\n", clear=True)
        self.execute_button.config(state=DISABLED)

        thread = threading.Thread(target=self._run_command_and_update_gui, args=(command_str, output_text))
        thread.daemon = True
        thread.start()

    def _run_command_and_update_gui(self, command: str, output_widget: ScrolledText):
        _, output = execute_command(command)
        self.root.after(0, self._update_output_text, output_widget, output, False)
        self.root.after(0, lambda: self.execute_button.config(state=NORMAL))

    def _update_output_text(self, widget: ScrolledText, result: str, clear: bool):
        widget.text.config(state=NORMAL)
        if clear:
            widget.delete("1.0", END)
        widget.insert(END, result)
        widget.text.config(state=DISABLED)
        widget.see(END)
        
    def _add_command(self, cmd_file: Path, listbox: tk.Listbox):
        title = simpledialog.askstring("Add Command", "Enter a title for the new command:", parent=self.root)
        if title == "": return

        command_type = "ADB" if cmd_file == ADB_COMMANDS_FILE else "SCRCPY"
        prompt = f"Enter the {command_type} command arguments:"
        raw_command = simpledialog.askstring("Add Command", prompt, parent=self.root)
        if raw_command == "": return

        self.command = {"title": title, "type": command_type, "command": raw_command}
        save_commands_to_file(cmd_file, self.command)
        self._refresh_command_list(cmd_file, listbox)

    def _delete_command(self, cmd_file: Path, listbox: tk.Listbox):
        if not listbox.curselection():
            messagebox.showwarning("No Selection", "Please select a command to delete.")
            return
        selected_title = listbox.get(listbox.curselection())

        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete '{selected_title}'?"):
            try:
                # Read all lines, filter out the one to delete, and write back
                with open(cmd_file, "r", encoding='utf-8') as f_read:
                    lines = f_read.readlines()
                
                with open(cmd_file, "w", encoding='utf-8') as f_write:
                    for line in lines:
                        # Check if the line contains the selected title, case-insensitively for robustness
                        # and ensure it's a command line, not a comment or empty line
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
