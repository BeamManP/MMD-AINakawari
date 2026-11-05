@echo off
rem AINakawari: puts MMDPlugin next to MikuMikuDance.exe (and moves MME into plugin\mme). See MMD-AINakawari\app\tools\install_plugin.py.
"%~dp0MMD-AINakawari\python\python.exe" -I "%~dp0MMD-AINakawari\app\tools\install_plugin.py" "%~dp0."
pause
