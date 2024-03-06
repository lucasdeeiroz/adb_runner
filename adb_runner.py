import subprocess
import argparse
import platform
import os
import sys
import re

def inline_cmd(comando):
    """
    Runs commands inline, returning an error or an output.
    """
    process = subprocess.Popen(comando, shell=True, stdout=subprocess.PIPE)
    output, err = process.communicate()
    if err:
        print(f"Error executing command: {err}")
        return None
    return output

def get_udids():
    """
    Runs adb devices command and filter the result to obtain a list of Android devices connected to ADB.
    """
    cmd = "adb devices"
    devices = inline_cmd(cmd)
    print("Identifying Android devices connected to the computer...\n\n")
    lines = devices.decode("utf-8").splitlines()
    udids = []
    for line in lines:
        if "List of devices attached" in line:
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1] != "offline" and parts[1] != "unauthorized":
            udids.append(parts[0])
    print(udids)
    print("\n==================================================")
    return udids

def get_android_version(udid):
    """
    Runs adb shell getprop command and filter the result to abtain the device's Android version.
    """
    print(f"\n\nDISPOSTIVO {udid}:")
    cmd = f"adb -s {udid} shell getprop ro.build.version.release"
    android_version = inline_cmd(cmd)
    print(f"\nIdentifying device Android version...")
    version_numbers = re.sub(r"[^\d\.]", "", android_version.decode("utf-8"))
    return version_numbers

def open_cmd_window(comando):
    """
    Runs command on another cmd window, independently. That means that the script does not wait for the command to finish execution.
    """
    subprocess.run(["start", "cmd", "/K", comando], shell=True, creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_BREAKAWAY_FROM_JOB)

def run_command(udids, command):
    """
    Runs your command for each device recognized by ADB in parallel
    If you set more than one argument for this script, do not forget to call it in the run_command function above
    """
    print(f"\nStarting ADB Runner script\n")
    print("==================================================")
    for udid in udids:
        android_version = get_android_version(udid)
        print(f"Android {android_version}!")
        # The execution command is located here:
        my_command = f"echo {udid} - Android {android_version} && {command}"
        print(f"Running your command on this device in another window...")
        open_cmd_window(my_command)
        print(f"Check your command execution in the separate cmd window\n\n")
        print("==================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a command on all ADB connected devices.")
    parser.add_argument("-c", "--command", required=True, help="Command to run")
    # If you need more arguments, you can add them here. Don't forget to pass them in the run_command() function below.
    args = parser.parse_args()

    udids = get_udids()
    if udids:
        run_command(udids, args.command)
    else:
        print("No Android devices connected or online on ADB.")
    print("\n\nPress any key to exit...")
    input()