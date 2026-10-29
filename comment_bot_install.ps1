# One-time setup for the comment bot (comment_bot.py) on an always-on PC.
# 1) Asks for the Anthropic API key once if .env has none (hidden input).
# 2) Registers a task that starts the bot at every logon and restarts it if it stops.
# Run only on ONE PC: two running copies of the same Telegram bot conflict.
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path $py) "pythonw.exe"

& $py -m pip install -q anthropic pydantic requests pillow
$hasKey = (Test-Path ".env") -and (Select-String -Path ".env" -Pattern "^ANTHROPIC_API_KEY=" -Quiet)
if (-not $hasKey) { & $py comment_bot.py --set-key }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "comment_bot.py" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-comment-bot" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Comment ideas bot for content-lab (never posts comments itself)" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-comment-bot"
Write-Host "OK: comment bot is running (log: data\comment_bot.log). Send a Threads link to the bot."
