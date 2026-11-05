@echo off
rem For the fast mode of AINakawari. The setup puts this file in the Kimodo folder (paths.server_cmd() in mmd_ainakawari/paths.py).
rem Kimodo text encoder server (LLM2Vec / Llama-3-8B) on 127.0.0.1:9550. kimodo_gen asks this first.
rem Every path is relative to this file's folder (%~dp0 ends with a backslash).
rem TMP folder must be inside the Kimodo folder (Gradio refuses to serve files outside the working dir).
cd /d "%~dp0"
set "HF_HUB_CACHE=%~dp0hf_cache"
rem Llama is read from text_encoders (tools/prepare_text_encoder.py), not from the gated meta-llama repo.
set "TEXT_ENCODERS_DIR=%~dp0text_encoders"
rem READY is written last by prepare_text_encoder.py. Without it the folder is half-made (and may still point at meta-llama).
if not exist "%TEXT_ENCODERS_DIR%\READY" (
  echo The text encoder is not ready: "%TEXT_ENCODERS_DIR%\READY" is missing. Run tools\prepare_text_encoder.py again.
  pause
  exit /b 1
)
set "TEXT_ENCODER_TMP_FOLDER=%~dp0te_tmp"
set GRADIO_SERVER_NAME=127.0.0.1
set PYTHONUTF8=1
"%~dp0.venv\Scripts\kimodo_textencoder.exe"
