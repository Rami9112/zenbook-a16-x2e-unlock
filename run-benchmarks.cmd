@echo off
setlocal
cd /d "%~dp0"

python "%~dp0benchmarks\verify_and_benchmark.py"
echo.
pause
