Come avviare il progetto!!!!

#1 term
cd trading-bot
pip install -r requirements.txt

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

#2 term

cd frontend

python -m http.server 3000
