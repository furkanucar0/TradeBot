# Trading bot hizmetlerini durdurur ve Görev Zamanlayıcısı kayıtlarını siler.
# Çalıştır:  powershell -ExecutionPolicy Bypass -File uninstall-services.ps1

$names = @("TradingBotBackend", "TradingBotFetcher", "TradingBotTelegram", "TradingBotFrontend")

foreach ($n in $names) {
    try {
        Stop-ScheduledTask -TaskName $n -ErrorAction Stop
        Write-Host "[OK] Durduruldu: $n"
    } catch {}
    try {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] Kaldirildi: $n" -ForegroundColor Green
    } catch {
        Write-Host "[--] Zaten yok: $n" -ForegroundColor Yellow
    }
}
