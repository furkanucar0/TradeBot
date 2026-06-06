$pythonPath = Resolve-Path (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
$scriptPath = Join-Path $PSScriptRoot 'zip_loader.py'
& $pythonPath.Path $scriptPath
