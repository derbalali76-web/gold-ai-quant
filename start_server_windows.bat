@echo off
REM GOLD AI QUANT - تشغيل الخادم على ويندوز
cd /d %~dp0backend
if not exist .venv (python -m venv .venv)
call .venv\Scripts\activate
pip install -q -r requirements.txt
REM set TWELVEDATA_API_KEY=ضع_مفتاحك_هنا
python -m uvicorn --factory goldquant.api:create_app --host 0.0.0.0 --port 8000
