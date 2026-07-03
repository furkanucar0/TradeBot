# MarginTrader — Telegram Uzaktan Kontrol (elle çalıştırma)
# NOT: install-services.ps1 kurulduysa telegram bot zaten hizmet olarak çalışır;
# bu script yalnızca hizmet YOKKEN veya durdurulmuşken elle çalıştırmak içindir.
$t = Get-ScheduledTask -TaskName "TradingBotTelegram" -ErrorAction SilentlyContinue
if ($t -and $t.State -eq "Running") {
    Write-Host "TradingBotTelegram hizmeti zaten calisiyor." -ForegroundColor Yellow
    Write-Host "Ikinci kopya Telegram getUpdates cakismasina (409) yol acar. Cikiliyor."
    exit 1
}
Set-Location "$PSScriptRoot\backend"
& python telegram_bot.py
