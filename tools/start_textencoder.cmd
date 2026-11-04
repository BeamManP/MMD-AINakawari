@echo off
rem AIナカワリの高速モード用。このファイルを F:\kimodo\ に置く（窓の「サーバーを起動」がこれを開く。mmd_ainakawari/app.py の SERVER_CMD）。
rem Kimodo text encoder server (LLM2Vec / Llama-3-8B) on 127.0.0.1:9550. kimodo_gen asks this first.
rem TMP folder must be inside F:\kimodo (Gradio refuses to serve files outside the working dir).
cd /d F:\kimodo
set HF_HUB_CACHE=F:\kimodo\hf_cache
set TEXT_ENCODER_TMP_FOLDER=F:\kimodo\te_tmp
set GRADIO_SERVER_NAME=127.0.0.1
set PYTHONUTF8=1
.venv\Scripts\kimodo_textencoder.exe
