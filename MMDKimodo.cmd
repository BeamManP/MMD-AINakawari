@echo off
rem MMDKimodo window. Runs with the mmd-mcp Python (it has the MMD bridge). Kimodo itself runs in F:\kimodo.
cd /d E:\Projects\MMDKimodo
start "" "E:\Projects\mmd-mcp\.venv\Scripts\pythonw.exe" -m mmdkimodo.app
