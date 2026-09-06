@echo off
setlocal
set "FUSION_CLI_DIR=%~dp0"
set "FUSION_CLI_PYTHON=%FUSION_CLI_DIR%.venv\Scripts\python.exe"
if not exist "%FUSION_CLI_PYTHON%" (
  >&2 echo fusion_cli: CLI environment not found. Run: py -m venv "%FUSION_CLI_DIR%.venv" ^&^& "%FUSION_CLI_PYTHON%" -m pip install -r "%FUSION_CLI_DIR%requirements.txt"
  exit /b 1
)
"%FUSION_CLI_PYTHON%" "%FUSION_CLI_DIR%fusion_cli.py" %*
exit /b %ERRORLEVEL%
