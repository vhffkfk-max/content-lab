# Keeps reel_listen.py running on this PC: starts at logon, restarts if it stops. Runs from its own clone so local_ai.py's reset can't disturb it.
# Re-run this after changing reel_listen.py (it pulls the latest code and restarts).
$dir = Join-Path $env:USERPROFILE "content-lab-reel"
if (-not (Test-Path $dir)) { git clone -q --depth 1 --single-branch --branch main "https://github.com/vhffkfk-max/content-lab.git" $dir }
Stop-ScheduledTask -TaskName "content-lab-reel-listen" -ErrorAction SilentlyContinue
git -C $dir fetch -q --depth 1 origin main
git -C $dir reset -q --hard origin/main
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "reels\reel_listen.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-reel-listen" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Picks up site video-lab requests within seconds (content-lab)" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-reel-listen"
Write-Host "OK: reel listener is running (log: ~\.content-lab-ai\reel_listen.log)."
