# Keeps the free Threads crawler (threads_watch.py --loop) running on this PC: starts at logon, restarts if it stops.
# Every 5 minutes it opens only what is due (a few accounts + posts whose next check time has come), so nothing is crawled twice.
Set-Location -LiteralPath $PSScriptRoot
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) "pythonw.exe"

Stop-ScheduledTask -TaskName "content-lab-threads-watch" -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $pyw -Argument "threads_watch.py --loop" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-threads-watch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Free Threads view tracker for content-lab (logged-out pages only, every 5 minutes)" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-threads-watch"
Write-Host "OK: threads crawler is running every 5 minutes (log: data\threads_watch.log)."
