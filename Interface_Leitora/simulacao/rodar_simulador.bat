@echo off
setlocal

cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Iniciando o Simulador OSL na COM6...
"%PYTHON%" "simulacao\simulador_osl.py"

if errorlevel 1 (
    echo.
    echo O simulador foi encerrado com erro.
    pause
)

endlocal
