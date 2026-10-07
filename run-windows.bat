@echo off
rem Run Uplink-9 on a Windows PC for testing. USB, VPN and power controls need the Linux device.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || (echo Install Python 3 from python.org first. & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python -m uplink
