# Registers the free Threads crawler (threads_watch.py) to run every 3 hours on this PC.
# Each run: scan watched accounts + recent collected posts, measure views, push output/site/thx_live*.json.
Set-Location -LiteralPath $PSScriptRoot
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) "pythonw.exe"

$action = New-ScheduledTaskAction -Execute $pyw -Argument "threads_watch.py" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 3)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 40) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-threads-watch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Free Threads view tracker for content-lab (logged-out pages only)" -Force | Out-Null
Write-Host "OK: threads crawler runs every 3 hours (log: data\threads_watch.log)."
