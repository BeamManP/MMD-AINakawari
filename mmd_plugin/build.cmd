@echo off
rem Build the menu DLL loaded into MMD (Visual Studio x64 C++ tools).
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo Install Visual Studio Build Tools with Desktop development with C++.
  exit /b 1
)
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "MMDK_VS=%%i"
if not defined MMDK_VS exit /b 1
call "%MMDK_VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
pushd "%~dp0"
if not exist "bin" mkdir "bin"
if not exist "build" mkdir "build"
cl /nologo /utf-8 /std:c++17 /O2 /MT /LD /W4 /WX /DUNICODE /D_UNICODE /Fo"build\menu_bridge.obj" /Fe"bin\mmdkimodo_menu.dll" "menu_bridge.cpp" /link user32.lib /IMPLIB:"build\mmdkimodo_menu.lib"
set "MMDK_RESULT=%ERRORLEVEL%"
popd
exit /b %MMDK_RESULT%
