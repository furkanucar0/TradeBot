Push-Location .\backend
if (Test-Path '.venv\Scripts\Activate.ps1') {
    Write-Host 'Activating Python virtual environment...'
    . .\.venv\Scripts\Activate.ps1
}
Write-Host 'Starting backend at http://localhost:8000'
$env:PYTHONUNBUFFERED = '1'
python .\run.py
Pop-Location
