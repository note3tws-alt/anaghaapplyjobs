<#
  Creates the Windows Task Scheduler jobs.
  - "AnaghaJobBot Run": Monday-Saturday at the time in config\settings.yaml (Asia/Dubai), no Sunday.
  - "AnaghaJobBot Telegram" (with -Telegram): starts the Telegram approval listener at sign-in.
  Run again after changing the schedule in the dashboard.
      powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 [-Telegram]
#>
param([switch]$Telegram)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { throw "Run scripts\windows\install.ps1 first." }

# Read the schedule from settings
$json = & $vpy -c "import json; from jobbot.config import load_settings; print(json.dumps(load_settings()['schedule']))"
$sched = $json | ConvertFrom-Json
$hh, $mm = $sched.time.Split(":")
$dayNames = @{Mon="Monday"; Tue="Tuesday"; Wed="Wednesday"; Thu="Thursday"; Fri="Friday"; Sat="Saturday"; Sun="Sunday"}
$order = @("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")

# Convert Dubai time to this PC's local time (handles a PC set to another time zone).
$dubai = [TimeZoneInfo]::FindSystemTimeZoneById("Arabian Standard Time")
$probe = [DateTime]::SpecifyKind((Get-Date -Year 2026 -Month 11 -Day 16 -Hour ([int]$hh) -Minute ([int]$mm) -Second 0), "Unspecified")  # a Monday
$local = [TimeZoneInfo]::ConvertTime($probe, $dubai, [TimeZoneInfo]::Local)
$shift = ($local.Date - $probe.Date).Days
$days = foreach ($d in $sched.days) {
    $i = [Array]::IndexOf($order, $dayNames[$d.Substring(0,3)])
    $order[($i + $shift + 7) % 7]
}
Write-Host ("Dubai {0} on {1} = local {2:HH:mm} on {3}" -f $sched.time, ($sched.days -join ","), $local, ($days -join ","))

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$Root\scripts\windows\run_jobbot.ps1`"" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $local.ToString("HH:mm")
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)
# Interactive: runs in Anagha's signed-in session so the browser can use her saved Indeed sign-in.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "AnaghaJobBot Run" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Searches Indeed UAE and prepares job applications for Anagha" -Force | Out-Null
Write-Host "Registered 'AnaghaJobBot Run'." -ForegroundColor Green

if ($Telegram) {
    $tAction = New-ScheduledTaskAction -Execute $vpy.Replace("python.exe", "pythonw.exe") -Argument "-m jobbot telegram" -WorkingDirectory $Root
    $tTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $tSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName "AnaghaJobBot Telegram" -Action $tAction -Trigger $tTrigger -Settings $tSettings `
        -Principal $principal -Description "Telegram Approve/Skip buttons for Anagha's job applications" -Force | Out-Null
    Start-ScheduledTask -TaskName "AnaghaJobBot Telegram"
    Write-Host "Registered and started 'AnaghaJobBot Telegram'." -ForegroundColor Green
}

Write-Host ""
Write-Host "Keep the PC switched on (sleep is OK: the task wakes it), signed in, and connected to the internet at the scheduled time."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName 'AnaghaJobBot Run'"
