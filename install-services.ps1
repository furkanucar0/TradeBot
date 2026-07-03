# Trading bot bileşenlerini Windows Görev Zamanlayıcısı hizmetlerine çevirir.
# Çalıştır:  powershell -ExecutionPolicy Bypass -File install-services.ps1
#
# Kurulan görevler (oturum açılışında otomatik başlar, çökerse 1 dk sonra yeniden başlar):
#   TradingBotBackend  -> backend/api.py        (FastAPI, port 8000)
#   TradingBotFetcher  -> backend/live_fetcher.py (1m mum toplayıcı)
#   TradingBotTelegram -> backend/telegram_bot.py (uzaktan kontrol)
#   TradingBotFrontend -> frontend Vite dev sunucusu (port 5173)
#
# Loglar: backend/logs/<bileşen>.log
# Kaldırmak için: uninstall-services.ps1

$ErrorActionPreference = "Stop"

$root       = $PSScriptRoot
$pythonw    = Join-Path $root ".venv\Scripts\pythonw.exe"
$backendDir = Join-Path $root "backend"
$wrapper    = Join-Path $backendDir "run_service.py"

if (-not (Test-Path $pythonw)) {
    Write-Host "HATA: $pythonw bulunamadi. Once sanal ortami kurun." -ForegroundColor Red
    exit 1
}

$tasks = @(
    @{ Name = "TradingBotBackend";  Script = "api.py" },
    @{ Name = "TradingBotFetcher";  Script = "live_fetcher.py" },
    @{ Name = "TradingBotTelegram"; Script = "telegram_bot.py" },
    @{ Name = "TradingBotFrontend"; Script = "frontend" }
)

foreach ($t in $tasks) {
    $action  = New-ScheduledTaskAction -Execute $pythonw `
                 -Argument "`"$wrapper`" $($t.Script)" `
                 -WorkingDirectory $backendDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet `
                  -RestartCount 999 `
                  -RestartInterval (New-TimeSpan -Minutes 1) `
                  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
                  -StartWhenAvailable `
                  -MultipleInstances IgnoreNew `
                  -AllowStartIfOnBatteries `
                  -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName $t.Name -Action $action `
        -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "[OK] Gorev kaydedildi: $($t.Name)" -ForegroundColor Green
}

Write-Host ""
$answer = "e"
if ($args -notcontains "-Start") {
    $answer = Read-Host "Hizmetler simdi baslatilsin mi? (e/h)"
}
if ($answer -eq "e" -or $args -contains "-Start") {
    foreach ($t in $tasks) {
        Start-ScheduledTask -TaskName $t.Name
        Write-Host "[OK] Baslatildi: $($t.Name)" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Durum kontrolu:  Get-ScheduledTask -TaskName 'TradingBot*' | Format-Table TaskName, State"
Write-Host "Loglar        :  backend\logs\"
