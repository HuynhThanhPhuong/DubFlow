"""Native Windows integration. Dialog runs in an isolated STA subprocess."""
import json
import os
from pathlib import Path
import shutil
import subprocess

def pick_folder(initial_dir=None):
    if os.name != 'nt':
        raise ValueError('Chọn thư mục gốc chỉ hỗ trợ Windows trên máy này.')
    executable = shutil.which('pwsh') or shutil.which('powershell')
    if not executable:
        raise ValueError('Không tìm thấy PowerShell để mở hộp chọn thư mục.')
    script = '''Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Chọn thư mục xuất DubFlow'
$d.ShowNewFolderButton = $true
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(1,1)
$owner.Opacity = 0
$owner.Show()
if ($env:DUBFLOW_PICK_INITIAL) { $d.SelectedPath = $env:DUBFLOW_PICK_INITIAL }
try {
 if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  ConvertTo-Json -Compress -InputObject $d.SelectedPath
 } else { 'null' }
} finally { $d.Dispose(); $owner.Dispose() }
'''
    env = os.environ.copy()
    env['DUBFLOW_PICK_INITIAL'] = str(initial_dir or '')
    try:
        result=subprocess.run([executable,'-NoProfile','-NonInteractive','-STA','-Command',script],env=env,capture_output=True,timeout=300)
        if result.returncode:
            raise ValueError('Không mở được hộp chọn thư mục Windows.')
        value=json.loads(result.stdout.decode('utf-8-sig').strip())
        if value is not None and (not isinstance(value,str) or not Path(value).is_dir()):
            raise ValueError('Thư mục đã chọn không hợp lệ.')
        return value
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):
        raise ValueError('Không mở được hộp chọn thư mục Windows hoặc đã quá thời gian.') from None

def open_folder(path):
    path=Path(path).resolve()
    if not path.is_dir():
        raise ValueError('Thư mục xuất chưa tồn tại.')
    if os.name != 'nt':
        raise ValueError('Mở thư mục chỉ hỗ trợ Windows trên máy này.')
    try:
        # Absolute path is a single argv entry, never interpreted as shell code.
        subprocess.Popen([str(Path(os.environ.get('WINDIR','C:/Windows'))/'explorer.exe'),str(path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except OSError:
        raise ValueError('Không mở được thư mục trong Windows Explorer.') from None
