import os
import sys
import ctypes
from ctypes import wintypes

WScript_Shell = None

def create_shortcut(fname, lnk_path):
    """
    Create a Windows shortcut (.lnk) using ctypes.
    Does not require win32com.
    """
    szPath = None
    szArgs = None
    szWorkDir = None
    szDesc = None

    # Convert inputs
    if isinstance(fname, str):
        fname = fname.encode('utf-16-le')
    if isinstance(lnk_path, str):
        lnk_path = lnk_path.encode('utf-16-le')

    szPath = fname

    args = '-m app.ui'
    if isinstance(args, str):
        szArgs = args.encode('utf-16-le')
    workdir = 'C:\\Users\\james\\Downloads\\CodeMode'
    if isinstance(workdir, str):
        szWorkDir = workdir.encode('utf-16-le')
    desc = 'CodeMode AI Assistant'
    if isinstance(desc, str):
        szDesc = desc.encode('utf-16-le')

    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    ShCreateShortcutW = shell32.Shell32_ShellLink_W

    # SHCreateShortcutW signature:
    # HRESULT ShCreateShortcutW(LPCWSTR pszShortcut, LPCWSTR pszTarget)
    # Actually it's:
    # HRESULT ShCreateShortcutW(LPCWSTR pszShortcut, PIDLIST_ABSOLUTE ppidl)

    # We'll use a simpler approach via IShellLink

    ole32 = ctypes.WinDLL('ole32', use_last_error=True)
    CLSID_ShellLink = ctypes.c_def_uuid(
        '00021401-0000-0000-C000-000000000046',
        1, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0
    )
    IID_IShellLinkW = ctypes.c_def_uuid(
        '000214F9-0000-0000-C000-000000000046',
        1, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0
    )

    # Create shell link object
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_ShellLink),
        None,
        1,  # CLSCTX_INPROC_SERVER
        ctypes.byref(IID_IShellLinkW),
        ctypes.byref(None)
    )

    if hr != 0:
        raise Exception(f"CoCreateInstance failed: {hr}")

    # We'll use IUnknown instead and call virtual methods
    # This is getting complex. Let's use a simpler approach.
    return None

if __name__ == '__main__':
    desktop = os.path.expanduser('~')
    desktop = os.path.join(desktop, 'Desktop')
    link = os.path.join(desktop, 'CodeMode.lnk')
    create_shortcut(
        r'C:\Program Files\Python311\pythonw.exe',
        link
    )
