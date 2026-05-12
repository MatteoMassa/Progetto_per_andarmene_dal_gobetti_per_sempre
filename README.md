Come avviare il progetto!!!!

#1 term

cd trading-bot

pip install -r requirements.txt

cd backend

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

#2 term

cd trading-bot/frontend

python -m http.server 3000

http://localhost:3000
