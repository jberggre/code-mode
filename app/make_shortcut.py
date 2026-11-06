#!/usr/bin/env python3
"""Create a Windows shortcut for launching the CodeMode app.

This script uses the WScript.Shell COM object to create a .lnk file
on the user's desktop. It requires no third-party libraries."""
import os
import sys
import pythoncom
import win32com.client

def main():
    # Get the desktop folder path
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    shortcut_path = os.path.join(desktop, 'CodeMode.lnk')
    
    # Target executable
    target = r'C:\Program Files\Python311\pythonw.exe'
    
    # Arguments to pass to the executable
    arguments = '-m app.ui'
    
    # Working directory (where the app is located)
    working_dir = r'C:\Users\james\Downloads\CodeMode'
    
    # Description of the shortcut
    description = 'CodeMode AI Assistant'
    
    # Create the COM object
    shell = win32com.client.Dispatch('WScript.Shell')
    
    # Create a shortcut object
    shortcut = shell.CreateShortcut(shortcut_path)
    
    # Set the properties
    shortcut.TargetPath = target
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = working_dir
    shortcut.Description = description
    
    # Save the shortcut
    shortcut.Save()
    
    print(f'Shortcut created: {shortcut_path}')

if __name__ == '__main__':
    main()
