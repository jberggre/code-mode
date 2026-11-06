import os
desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
bat_path = os.path.join(desktop, 'CodeMode.bat')
with open(bat_path, 'w') as f:
    f.write(at_echo_off + cd_d + pythonw)
print('Created at:', bat_path, 'exists:', os.path.exists(bat_path))