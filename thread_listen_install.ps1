# Keeps thread_listen.py running on this PC: starts at logon, restarts if it stops. Runs from its own clone so local_ai.py's reset never touches it.
# Re-run this after changing thread_listen.py (it pulls the latest code and restarts).
$dir = Join-Path $env:USERPROFILE "content-lab-thread"
if (-not (Test-Path $dir)) { git clone -q --depth 1 --single-branch --branch main "https://github.com/vhffkfk-max/content-lab.git" $dir }
Stop-ScheduledTask -TaskName "content-lab-thread-listen" -ErrorAction SilentlyContinue
git -C $dir fetch -q --depth 1 origin main
git -C $dir reset -q --hard origin/main
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "thread_listen.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-thread-listen" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Picks up site thread-post requests within seconds (content-lab)" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-thread-listen"
Write-Host "OK: thread listener is running (log: ~\.content-lab-ai\thread_listen.log)."
