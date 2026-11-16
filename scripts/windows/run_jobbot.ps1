# Called by Task Scheduler. Runs one job-bot session and keeps a log.
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Root
$log = Join-Path $Root "data\logs\scheduled.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
"==== $(Get-Date -Format s) start ====" | Out-File -Append -Encoding utf8 $log
& "$Root\.venv\Scripts\python.exe" -m jobbot run --scheduled *>> $log
"==== $(Get-Date -Format s) exit $LASTEXITCODE ====" | Out-File -Append -Encoding utf8 $log
exit $LASTEXITCODE
