param([string]$job, [int]$rounds = 5)
$env:PYTHONIOENCODING = 'utf-8'
$s = 'D:\DuAnKhoiNghiep\DubFlow\bench\run_v60.py'
for ($r = 1; $r -le $rounds; $r++) {
    & D:\DuAnKhoiNghiep\DubFlow\repo-tests\clone-voxcpm\Scripts\python.exe $s gen $job 2>&1 | Select-String '^(Trace|\w+Error)'
    $out = & D:\OmniVoice\venv\Scripts\python.exe $s pick $job 2>$null
    "== round $r"; $out
    if (-not ($out -match 'ROUND_NEEDED')) { break }
}
