import subprocess
import re
import os
import sys
import time
from typing import List, Tuple, Union
import urllib.request
import zipfile
import json


class Style:
    """Define colors for the terminal."""
    RED = "\033[31m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    RESET = "\033[0m"


def execute_command(command: str, max_attempts: int = 3) -> Union[str, None]:
    """Executes a command in the shell and returns the output."""
    attempt = 0
    while attempt < max_attempts:
        if "scrcpy.exe" in command:
            """Abre uma janela de prompt de comando e executa o comando."""
            try:
                subprocess.Popen(f'start cmd /K "{command}"', shell=True)
                return "Scrcpy started in a new window."  # Return immediately after starting scrcpy
            except FileNotFoundError:
                print(f"{Style.RED}Erro: O comando 'start' não foi encontrado.{Style.RESET} Certifique-se de que está executando em um sistema Windows.")
                return None
            except Exception as e:
                print(f"{Style.RED}Erro ao executar o comando: {e}{Style.RESET}")
                return None
        else:
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, err = process.communicate()
            try:
                if err:
                    err_str = err.decode('utf-8')
                    if err_str.startswith("* daemon not running"):
                        print(err_str)
                        print("ADB started. Trying again...")
                        time.sleep(2)
                        attempt += 1
                        continue
                    elif "device not found" in err_str:
                        print(f"{Style.RED}Device not found: {err_str}{Style.RESET}")
                        return None
                    else:
                        print(f"{Style.RED}Error executing the command: {err_str}{Style.RESET}")
                        try_again = input("Press any key to try again or Q to quit...").upper()
                        if try_again != "Q":
                            attempt += 1
                            continue
                        else:
                            return None
                if not output:
                    print(f"{Style.RED}Error executing the command: {command}{Style.RESET}")
                    print("Check if the tool is installed and configured correctly.")
                    print("See the README to install all the necessary tools.")
                    try_again = input("\nPress any key to try again or Q to quit...").upper()
                    if try_again != "Q":
                        attempt += 1
                        continue
                    else:
                        return None
                return output.decode("utf-8").strip()
            except UnicodeDecodeError:
                try:
                    return output.decode("latin-1").strip()
                except:
                    print(f"{Style.RED}Error decoding output. Please check your system's default encoding.{Style.RESET}")
                    return None
    print(f"{Style.RED}Error executing the command after {max_attempts} attempts.{Style.RESET}")
    return None


def get_devices() -> Union[List[Tuple[str, str, str]], None]:
    """Gets the UDIDs, versions, and models of connected Android devices."""
    while True:
        print("Identifying devices connected to the computer...")
        recognized_devices = execute_command("adb devices")
        if not recognized_devices:
            print(f"{Style.RED}Error executing the 'adb devices' command.{Style.RESET}")
            print("Check if ADB is installed and configured correctly.")
            print("\n==================================================\n")
            return None
        lines = recognized_devices.splitlines()
        devices = []
        for line in lines[1:]:  # Ignore the first line (header)
            parts = line.split()
            if len(parts) == 2 and parts[1] in ("device", "emulator"):
                udid = parts[0]
                android_version = get_android_version(udid)
                android_model = get_model(udid)
                if android_version and android_model:
                    devices.append((udid, android_version, android_model))
        if devices:
            print("\n==================================================\n")
            return devices
        else:
            print(f"{Style.RED}No Android devices detected.{Style.RESET} Connect a device to the computer and make sure USB Debugging is enabled.")  # noqa
            input("Press any key to try again...")
            print("\n==================================================\n")
            continue


def get_android_version(udid: str) -> Union[str, None]:
    """Gets the Android version of a specific device."""
    cmd = f"adb -s {udid} shell getprop ro.build.version.release"
    return execute_command(cmd)


def get_model(udid: str) -> Union[str, None]:
    """Gets the model of a specific device."""
    cmd = f"adb -s {udid} shell getprop ro.product.model"
    return execute_command(cmd)


def select_device(devices: List[Tuple[str, str, str]]) -> Union[str, None]:
    """Allows the user to select an Android device."""
    print("\nConnected devices:")
    for i, (udid, version, model) in enumerate(devices):
        print(f"{i + 1} - Android {version} - {model} ({udid})")

    while True:
        choice = input("Select the device number or 'Q' to exit: ").upper()
        if choice == "Q":
            return None
        try:
            index = int(choice) - 1
            if 0 <= index < len(devices):
                return devices[index][0]  # Returns the UDID
            else:
                print(f"{Style.RED}Invalid number.{Style.RESET}")
        except ValueError:
            print(f"{Style.RED}Invalid input.{Style.RESET}")


def load_commands_from_file(filename="useful_adb_commands.txt", scrcpy_folder="") -> dict:
    """Loads ADB commands from a text file."""
    commands = {}
    try:
        with open(filename, "r") as file:
            for i, line in enumerate(file):
                line = line.strip()
                if line and not line.startswith("//") and not line.isspace():  # Ignore empty lines and comments
                    title = line
                    if line.startswith("echo "):
                        title = line.split("&&")[0].replace("echo ", "").strip()
                    commands[str(i + 1)] = {"command": line.replace("{scrcpy_folder}", scrcpy_folder), "title": title}
    except FileNotFoundError:
        print(f"{Style.RED}Commands file '{filename}' not found.{Style.RESET}")
        return {}
    return commands


def execute_selected_command(udid: str, scrcpy_folder: str) -> None:
    """Executes an ADB command selected by the user."""
    commands_file = "useful_adb_commands.txt"
    predefined_commands = load_commands_from_file(commands_file, scrcpy_folder)
    next_command_number = len(predefined_commands) + 1

    print("\nPredefined commands:")
    for key, command_data in predefined_commands.items():
        print(f"{key} - {command_data['title'].format(udid=udid)}")
    print(f"{next_command_number} - Insert custom ADB shell command")
    print("Q - Exit")

    while True:
        choice = input("Select the command number or 'Q' to exit: ").upper()
        if choice == "Q":
            return

        if choice in predefined_commands:
            command = predefined_commands[choice]["command"].format(udid=udid)
        elif choice == str(next_command_number):
            command = input("Insert ADB shell command: ")
            title = input("Insert a title for this command: ")
            add_to_file = input("Do you want to add this command to the commands file? (Y/N): ").upper()
            if add_to_file == "Y":
                with open(commands_file, "a") as file:
                    file.write(f"\necho {title} && {command}")
                print(f"Command '{title}' added to {commands_file}")
                command = command.replace("{scrcpy_folder}", scrcpy_folder).format(udid=udid)
        else:
            print(f"{Style.RED}Invalid option.{Style.RESET}")
            continue

        print(f"\nExecuting: {Style.BLUE}{command}{Style.RESET} on device {udid}...")
        output = execute_command(command)

        if output:
            print(f"Output:\n{output}")
        else:
            print(f"{Style.RED}Failed to execute the command.{Style.RESET}")
        return


def check_and_download_scrcpy():
    """Checks if scrcpy is present and downloads it if not."""
    scrcpy_folder = None
    for folder in os.listdir("."):
        if folder.startswith("scrcpy") and os.path.isdir(folder):
            scrcpy_folder = folder
            break

    if scrcpy_folder:
        scrcpy_executable = os.path.join(scrcpy_folder, "scrcpy.exe")
        if os.path.exists(scrcpy_executable):
            return scrcpy_folder

    print("scrcpy not found. Downloading...")
    try:
        # Get the latest release info from GitHub API
        url = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
        response = urllib.request.urlopen(url)
        data = json.loads(response.read().decode())
        version = data["tag_name"]

        # Determine the correct download URL based on the OS
        if os.name == 'nt':  # Windows
            asset_name = f"scrcpy-win64-{version}.zip"
            download_url = None
            for asset in data["assets"]:
                if asset["name"] == asset_name:
                    download_url = asset["browser_download_url"]
                    break
            if not download_url:
                print(f"{Style.RED}Could not find the correct asset for Windows.{Style.RESET}")
                return False
        else:
            print(f"{Style.RED}Automatic download of scrcpy is only supported on Windows.{Style.RESET}")
            return False

        # Download the zip file
        zip_path = "scrcpy.zip"
        urllib.request.urlretrieve(download_url, zip_path)

        # Extract the zip file
        scrcpy_folder = f"scrcpy-win64-{version}"
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")

        # Rename the extracted folder to a consistent name
        extracted_folder = None
        for folder in os.listdir("."):
            if folder.startswith("scrcpy") and os.path.isdir(folder):
                extracted_folder = folder
                break

        if extracted_folder and extracted_folder != scrcpy_folder:
            os.rename(extracted_folder, scrcpy_folder)

        # Clean up the zip file
        os.remove(zip_path)

        print("scrcpy downloaded and extracted successfully.")
        return scrcpy_folder

    except urllib.error.URLError as e:
        print(f"{Style.RED}Error downloading scrcpy: {e.reason}{Style.RESET}")
        return False
    except zipfile.BadZipFile:
        print(f"{Style.RED}Error extracting scrcpy. The downloaded file may be corrupted.{Style.RESET}")
        return False

    except Exception as e:
        print(f"{Style.RED}Error downloading or extracting scrcpy: {e}{Style.RESET}")
        return False


if __name__ == "__main__":
    scrcpy_folder = check_and_download_scrcpy()
    if not scrcpy_folder:
        print("Failed to download scrcpy. Ensure you have the necessary tools installed manually.")
        sys.exit(1)

    while True:
        devices = get_devices()
        if not devices:
            print("No devices found. Exiting.")
            break

        udid = select_device(devices)
        if not udid:
            print("No device selected. Exiting.")
            break

        execute_selected_command(udid, scrcpy_folder)

        continuar = input("Do you want to execute another command? (Q/N): ").upper()
        if continuar != "Q" and continuar != "N":
            continue
        else:
            print("Exiting the script.")
            break