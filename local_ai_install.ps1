# One-time setup: run Claude jobs on this PC with the Max subscription (local_ai.py) instead of the paid API on GitHub.
# 1) Make a separate working clone (C:\Users\qkreo\content-lab-ai) so the dev folder is never touched.
# 2) Copy .env there (bot tokens for card-news alerts). 3) Register task "content-lab-ai" every 5 minutes.
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dir = "C:\Users\qkreo\content-lab-ai"
$pyw = "C:\Users\qkreo\AppData\Local\Programs\Python\Python312\pythonw.exe"

if (-not (Test-Path "$dir\.git")) {
    git clone -q https://github.com/vhffkfk-max/content-lab.git $dir
}
if (Test-Path "$src\.env") { Copy-Item "$src\.env" "$dir\.env" -Force }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "local_ai.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-ai" -Action $action -Trigger $trigger -Settings $settings `
    -Description "content-lab: Claude jobs via Claude Code (Max subscription), every 5 minutes" -Force | Out-Null
Write-Host "OK: content-lab-ai runs every 5 minutes (log: $dir\data\local_ai.log)"
