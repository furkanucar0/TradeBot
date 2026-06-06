@echo off
set SCRIPT_DIR=%~dp0
set PYTHON=%SCRIPT_DIR%..\.venv\Scripts\python.exe
"%PYTHON%" "%SCRIPT_DIR%zip_loader.py"
