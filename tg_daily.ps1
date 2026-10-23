# Daily Telegram collection on this PC (run by Windows Task Scheduler at 07:00).
# Collect -> push data/telegram.json -> GitHub (telegram.yml) analyzes with Claude and redeploys the site.
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $PSScriptRoot "data\tg_daily.log"
"==== $(Get-Date -Format 'yyyy-MM-dd HH:mm') ====" | Out-File $log -Append -Encoding utf8
& git pull --rebase --autostash *>> $log
& "C:\Users\qkreo\AppData\Local\Programs\Python\Python312\python.exe" tg_collect.py *>> $log
if ($LASTEXITCODE -eq 0) {
    & git add data/telegram.json *>> $log
    & git commit -m "data: telegram $(Get-Date -Format 'yyyy-MM-dd')" *>> $log
    & git push *>> $log
}
