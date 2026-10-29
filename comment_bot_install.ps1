# One-time setup for the comment bot (comment_bot.py) on an always-on PC.
# Usually started by comment_bot_setup.bat (double-click), which passes -Python and -EnvFrom.
# 1) Adds missing keys from the USB .env, asks for the Anthropic API key once if none (hidden input).
# 2) Registers a task that starts the bot at every logon and restarts it if it stops.
# Run only on ONE PC: two running copies of the same Telegram bot conflict.
param([string]$Python, [string]$EnvFrom)
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$py = if ($Python) { $Python } else { (Get-Command python).Source }
$pyw = Join-Path (Split-Path $py) "pythonw.exe"

# Merge keys from the USB .env without overwriting ones already here (e.g. a key entered earlier). No BOM.
$envPath = Join-Path $PSScriptRoot ".env"
if ($EnvFrom -and (Test-Path -LiteralPath $EnvFrom)) {
    $text = if (Test-Path $envPath) { [IO.File]::ReadAllText($envPath) } else { "" }
    $have = $text -split "`r?`n" | ForEach-Object { ($_ -split "=", 2)[0].Trim() }
    $add = [IO.File]::ReadAllLines($EnvFrom) | Where-Object { $_ -match "^\s*[A-Za-z_]+=" -and (($_ -split "=", 2)[0].Trim() -notin $have) }
    if ($add) {
        if ($text -and -not $text.EndsWith("`n")) { $text += "`n" }
        [IO.File]::WriteAllText($envPath, $text + (($add -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
    }
}

& $py -m pip install -q --disable-pip-version-check anthropic pydantic requests pillow
$hasKey = (Test-Path $envPath) -and (Select-String -Path $envPath -Pattern "^ANTHROPIC_API_KEY=." -Quiet)
if (-not $hasKey) { & $py comment_bot.py --set-key }

Stop-ScheduledTask -TaskName "content-lab-comment-bot" -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $pyw -Argument "comment_bot.py" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "content-lab-comment-bot" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Comment ideas bot for content-lab (never posts comments itself)" -Force | Out-Null
Start-ScheduledTask -TaskName "content-lab-comment-bot"
Write-Host "OK: comment bot is running (log: data\comment_bot.log)."
