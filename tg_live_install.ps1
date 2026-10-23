# One-time setup for real-time Telegram collection (tg_live.py).
# 1) Log in once for the live program (enter the code Telegram sends you).
# 2) Replace the old 07:00 task with a task that starts tg_live.py at every logon and restarts it if it stops.
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$py = "C:\Users\qkreo\AppData\Local\Programs\Python\Python312\python.exe"
$pyw = "C:\Users\qkreo\AppData\Local\Programs\Python\Python312\pythonw.exe"

& $py tg_live.py --login
if ($LASTEXITCODE -ne 0) { Write-Host "Login failed. Run this script again."; exit 1 }

Unregister-ScheduledTask -TaskName "content-lab-telegram" -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $pyw -Argument "tg_live.py" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-telegram-live" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Real-time Telegram collection and alerts for content-lab" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-telegram-live"
Write-Host "OK: real-time collection is running (log: data\tg_live.log)"
