# Removes the scheduled tasks (the project and data stay).
foreach ($n in @("AnaghaJobBot Run", "AnaghaJobBot Telegram")) {
    if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false
        Write-Host "Removed $n"
    }
}
