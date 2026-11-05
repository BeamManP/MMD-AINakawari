@echo off
rem For the fast mode of AINakawari. Put this file in F:\kimodo\ (the window's server button opens it: SERVER_CMD in mmd_ainakawari/app.py).
rem Kimodo text encoder server (LLM2Vec / Llama-3-8B) on 127.0.0.1:9550. kimodo_gen asks this first.
rem TMP folder must be inside F:\kimodo (Gradio refuses to serve files outside the working dir).
cd /d F:\kimodo
set HF_HUB_CACHE=F:\kimodo\hf_cache
rem Llama is read from text_encoders (tools/prepare_text_encoder.py), not from the gated meta-llama repo.
set TEXT_ENCODERS_DIR=F:\kimodo\text_encoders
set TEXT_ENCODER_TMP_FOLDER=F:\kimodo\te_tmp
set GRADIO_SERVER_NAME=127.0.0.1
set PYTHONUTF8=1
.venv\Scripts\kimodo_textencoder.exe
