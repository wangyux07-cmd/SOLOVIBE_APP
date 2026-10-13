@echo off
REM Compatibility launcher for the active SoloVibe backend.
set "TASK_ROOT=%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%TASK_ROOT%\scripts\dev.ps1" -Service backend
exit /b %ERRORLEVEL%
