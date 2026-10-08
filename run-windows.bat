@echo off
rem Run Uplink-9 on a Windows PC for testing. USB, VPN and power controls need the Linux device.
rem   run-windows.bat          text mode in this window
rem   run-windows.bat --gui    graphics mode in its own window (mouse clicks act as taps; add --touch for touch controls)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || (echo Install Python 3 from python.org first. & pause & exit /b 1)
)
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m uplink %*
