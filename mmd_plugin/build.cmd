@echo off
rem Build plugin\MMD-AINakawari\MMD-AINakawari.dll for MMDPlugin (Visual Studio x64 C++ tools).
rem AINAKAWARI_SDK: folder of mmdplugin_dev_ver0.41_x64 (mmd_plugin.h, MMDPlugin.lib). Default: ..\work\mmdplugin\dev
setlocal
if not defined AINAKAWARI_SDK set "AINAKAWARI_SDK=%~dp0..\work\mmdplugin\dev"
if not exist "%AINAKAWARI_SDK%\mmd_plugin.h" (
  echo mmd_plugin.h not found in %AINAKAWARI_SDK%. Set AINAKAWARI_SDK to the MMDPlugin developer files.
  exit /b 1
)
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo Install Visual Studio Build Tools with Desktop development with C++.
  exit /b 1
)
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "AINAKAWARI_VS=%%i"
if not defined AINAKAWARI_VS exit /b 1
call "%AINAKAWARI_VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
pushd "%~dp0"
if not exist "bin" mkdir "bin"
if not exist "build\sdk\MMDPlugin" mkdir "build\sdk\MMDPlugin"
rem The header always enables the d3dx9 hook (MMDPluginDLL4), which needs d3dx9.h from the old DirectX SDK.
rem This plugin only uses MMDPluginDLL3, so build against a copy with that define replaced by a forward declaration
rem (create4/destroy4 at the end of the header still name MMDPluginDLL4).
powershell -NoProfile -Command "(Get-Content -LiteralPath $env:AINAKAWARI_SDK\mmd_plugin.h -Encoding UTF8) -replace '^#define MMDPLUGIN_D3DX9_HOOK.*$', 'struct MMDPluginDLL4;' | Set-Content -LiteralPath build\sdk\mmd_plugin.h -Encoding UTF8"
if errorlevel 1 (popd & exit /b 1)
copy /y "%AINAKAWARI_SDK%\MMDPlugin.lib" "build\sdk\MMDPlugin\MMDPlugin.lib" >nul
rem C++14: the header uses std::result_of and std::experimental::filesystem (2017 era).
cl /nologo /utf-8 /std:c++14 /O2 /MT /LD /EHsc /W4 /WX /DUNICODE /D_UNICODE /D_SILENCE_EXPERIMENTAL_FILESYSTEM_DEPRECATION_WARNING /I"build\sdk" /Fobuild\ /Fe"bin\MMD-AINakawari.dll" "nakawari_plugin.cpp" "nakawari_panel.cpp" /link user32.lib gdi32.lib /LIBPATH:"build\sdk" /IMPLIB:"build\MMD-AINakawari.lib"
set "AINAKAWARI_RESULT=%ERRORLEVEL%"
popd
exit /b %AINAKAWARI_RESULT%
