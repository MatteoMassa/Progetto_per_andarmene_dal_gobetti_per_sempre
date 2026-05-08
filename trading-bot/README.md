# 📈 Trading Bot Dashboard — Paper Trading

Piattaforma di trading simulato con strategia EMA Crossover.
**100% gratuito** — usa yfinance (Yahoo Finance), nessuna API key necessaria.

## Coppie monitorate
- **XAU/USD** — Oro (futures GC=F)
- **XAG/USD** — Argento (futures SI=F)
- **EUR/USD** — Euro/Dollaro
- **BTC/USD** — Bitcoin

## Strategia
**EMA Crossover 9/21**
- Se EMA(9) incrocia sopra EMA(21) → segnale **BUY**
- Se EMA(9) incrocia sotto EMA(21) → segnale **SELL**
- Ogni operazione usa il 5% del capitale disponibile

---

## ▶ Come avviare il progetto

### Requisiti
- Python 3.10+
- Un browser moderno

### 1. Avvia il Backend

```bash
cd backend

# Crea ambiente virtuale (consigliato)
python -m venv venv

# Attiva ambiente (Windows)
venv\Scripts\activate

# Attiva ambiente (Mac/Linux)
source venv/bin/activate

# Installa dipendenze
pip install -r requirements.txt

# Avvia il server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Il backend sarà disponibile su http://localhost:8000

### 2. Apri il Frontend

Apri semplicemente il file `frontend/index.html` nel browser.
Oppure avvia un server locale:

```bash
cd frontend
python -m http.server 3000
```

Poi vai su http://localhost:3000

---

## 📁 Struttura del progetto

```
trading-bot/
├── backend/
│   ├── main.py          # Server FastAPI + logica bot
│   ├── requirements.txt # Dipendenze Python
│   └── trading.db       # Database SQLite (creato automaticamente)
└── frontend/
    └── index.html       # Dashboard React (file singolo)
```

---

## ⚙️ Configurazione (backend/main.py)

Puoi modificare questi parametri in cima al file:

```python
EMA_FAST = 9          # EMA veloce (periodi)
EMA_SLOW = 21         # EMA lenta (periodi)
POLL_INTERVAL = 15    # Secondi tra aggiornamenti prezzi
INITIAL_BALANCE = 10000.0  # Capitale iniziale simulato ($)
LOT_SIZE_PCT = 0.05   # % del capitale per operazione (5%)
```

---

## ℹ️ Note

- I prezzi si aggiornano ogni ~15 secondi (limite Yahoo Finance)
- Il database SQLite viene creato automaticamente alla prima esecuzione
- Tutto è paper trading: nessun denaro reale viene movimentato
- Per resettare: elimina il file `backend/trading.db`
