"""
Trading Bot Backend - Paper Trading con EMA Crossover
Usa yfinance per i prezzi (gratis, nessuna API key)
"""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional
import yfinance as yf
import pandas as pd
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import threading
import time

# ─── Configurazione ───────────────────────────────────────────────
PAIRS = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "EUR/USD": "EURUSD=X",
    "BTC/USD": "BTC-USD",
}

EMA_FAST = 9    # EMA veloce (periodi)
EMA_SLOW = 21   # EMA lenta (periodi)
POLL_INTERVAL = 15  # secondi tra ogni aggiornamento prezzi
INITIAL_BALANCE = 10000.0  # capitale iniziale simulato in USD
LOT_SIZE_PCT = 0.05  # 5% del capitale per operazione

# ─── Database SQLite ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("trading.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity REAL NOT NULL,
            pnl_usd REAL,
            pnl_pct REAL,
            status TEXT NOT NULL DEFAULT 'open',
            open_time TEXT NOT NULL,
            close_time TEXT,
            ema_fast_entry REAL,
            ema_slow_entry REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY,
            amount REAL NOT NULL
        )
    """)
    # Inserisci balance iniziale se non esiste
    c.execute("SELECT COUNT(*) FROM balance")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO balance (id, amount) VALUES (1, ?)", (INITIAL_BALANCE,))
    conn.commit()
    conn.close()

def get_balance() -> float:
    conn = sqlite3.connect("trading.db")
    c = conn.cursor()
    c.execute("SELECT amount FROM balance WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else INITIAL_BALANCE

def set_balance(amount: float):
    conn = sqlite3.connect("trading.db")
    c = conn.cursor()
    c.execute("UPDATE balance SET amount=? WHERE id=1", (amount,))
    conn.commit()
    conn.close()

def save_trade(trade: dict):
    conn = sqlite3.connect("trading.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO trades
        (id, pair, direction, entry_price, exit_price, quantity, pnl_usd, pnl_pct,
         status, open_time, close_time, ema_fast_entry, ema_slow_entry)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade["id"], trade["pair"], trade["direction"],
        trade["entry_price"], trade.get("exit_price"),
        trade["quantity"], trade.get("pnl_usd"), trade.get("pnl_pct"),
        trade["status"], trade["open_time"], trade.get("close_time"),
        trade.get("ema_fast_entry"), trade.get("ema_slow_entry")
    ))
    conn.commit()
    conn.close()

def get_open_trades() -> list:
    conn = sqlite3.connect("trading.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status='open' ORDER BY open_time DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_closed_trades() -> list:
    conn = sqlite3.connect("trading.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status='closed' ORDER BY close_time DESC LIMIT 100")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ─── Stato globale ─────────────────────────────────────────────────
prices: dict = {}          # prezzi attuali {pair: price}
ema_data: dict = {}        # {pair: {"fast": float, "slow": float, "prev_fast": float, "prev_slow": float}}
clients: list = []         # WebSocket connessi
bot_running = True

# ─── yfinance helpers ──────────────────────────────────────────────
def fetch_price(ticker: str) -> Optional[float]:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"Errore fetch {ticker}: {e}")
    return None

def fetch_history(ticker: str, period: str = "5d", interval: str = "15m") -> pd.Series:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval)
        return hist["Close"].dropna()
    except Exception as e:
        print(f"Errore history {ticker}: {e}")
        return pd.Series(dtype=float)

def compute_ema(series: pd.Series, span: int) -> float:
    if len(series) < span:
        return float(series.iloc[-1]) if len(series) > 0 else 0.0
    ema = series.ewm(span=span, adjust=False).mean()
    return float(ema.iloc[-1])

# ─── Logica EMA crossover ──────────────────────────────────────────
def check_signal(pair: str, closes: pd.Series) -> Optional[str]:
    """Restituisce 'BUY', 'SELL' o None"""
    if len(closes) < EMA_SLOW + 2:
        return None

    fast_now  = compute_ema(closes, EMA_FAST)
    slow_now  = compute_ema(closes, EMA_SLOW)
    fast_prev = compute_ema(closes.iloc[:-1], EMA_FAST)
    slow_prev = compute_ema(closes.iloc[:-1], EMA_SLOW)

    # Salva EMA correnti
    ema_data[pair] = {
        "fast": fast_now, "slow": slow_now,
        "prev_fast": fast_prev, "prev_slow": slow_prev
    }

    # Crossover rialzista: EMA fast passa sopra EMA slow
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "BUY"
    # Crossover ribassista: EMA fast passa sotto EMA slow
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SELL"
    return None

def open_trade(pair: str, direction: str, price: float, ema_fast: float, ema_slow: float):
    balance = get_balance()
    quantity = (balance * LOT_SIZE_PCT) / price
    trade = {
        "id": str(uuid.uuid4())[:8],
        "pair": pair,
        "direction": direction,
        "entry_price": price,
        "exit_price": None,
        "quantity": quantity,
        "pnl_usd": None,
        "pnl_pct": None,
        "status": "open",
        "open_time": datetime.now(timezone.utc).isoformat(),
        "close_time": None,
        "ema_fast_entry": ema_fast,
        "ema_slow_entry": ema_slow,
    }
    save_trade(trade)
    print(f"[BOT] Aperto {direction} su {pair} @ {price:.4f}")
    return trade

def close_trade(trade: dict, price: float):
    direction = trade["direction"]
    if direction == "BUY":
        pnl_usd = (price - trade["entry_price"]) * trade["quantity"]
        pnl_pct = ((price - trade["entry_price"]) / trade["entry_price"]) * 100
    else:
        pnl_usd = (trade["entry_price"] - price) * trade["quantity"]
        pnl_pct = ((trade["entry_price"] - price) / trade["entry_price"]) * 100

    trade.update({
        "exit_price": price,
        "pnl_usd": round(pnl_usd, 4),
        "pnl_pct": round(pnl_pct, 4),
        "status": "closed",
        "close_time": datetime.now(timezone.utc).isoformat(),
    })
    save_trade(trade)

    # Aggiorna balance
    balance = get_balance()
    set_balance(balance + pnl_usd)
    print(f"[BOT] Chiuso {trade['direction']} su {trade['pair']} @ {price:.4f} | P&L: {pnl_usd:+.2f}$ ({pnl_pct:+.2f}%)")
    return trade

# ─── Loop principale del bot ───────────────────────────────────────
def bot_loop():
    global prices
    print("[BOT] Avviato - strategia EMA crossover")
    while bot_running:
        for pair, ticker in PAIRS.items():
            try:
                closes = fetch_history(ticker)
                if closes.empty:
                    continue

                current_price = float(closes.iloc[-1])
                prices[pair] = current_price

                signal = check_signal(pair, closes)
                open_trades = [t for t in get_open_trades() if t["pair"] == pair]

                # Chiudi posizioni aperte in direzione opposta
                for trade in open_trades:
                    if signal == "BUY" and trade["direction"] == "SELL":
                        close_trade(trade, current_price)
                    elif signal == "SELL" and trade["direction"] == "BUY":
                        close_trade(trade, current_price)

                # Apri nuova posizione se non c'è già una aperta sullo stesso pair
                if signal and not any(t["pair"] == pair for t in get_open_trades()):
                    ema = ema_data.get(pair, {})
                    open_trade(pair, signal, current_price, ema.get("fast", 0), ema.get("slow", 0))

            except Exception as e:
                print(f"[BOT] Errore su {pair}: {e}")

        time.sleep(POLL_INTERVAL)

# ─── Broadcast WebSocket ───────────────────────────────────────────
async def broadcast(message: dict):
    dead = []
    for ws in clients:
        try:
            await ws.send_text(json.dumps(message))
        except:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)

async def price_broadcaster():
    """Invia aggiornamenti ai client ogni 5 secondi"""
    while True:
        await asyncio.sleep(5)
        if prices:
            open_trades = get_open_trades()
            closed_trades = get_closed_trades()
            balance = get_balance()

            # Calcola P&L live sulle posizioni aperte
            for trade in open_trades:
                pair = trade["pair"]
                price = prices.get(pair, trade["entry_price"])
                if trade["direction"] == "BUY":
                    trade["live_pnl_usd"] = round((price - trade["entry_price"]) * trade["quantity"], 4)
                    trade["live_pnl_pct"] = round(((price - trade["entry_price"]) / trade["entry_price"]) * 100, 4)
                else:
                    trade["live_pnl_usd"] = round((trade["entry_price"] - price) * trade["quantity"], 4)
                    trade["live_pnl_pct"] = round(((trade["entry_price"] - price) / trade["entry_price"]) * 100, 4)
                trade["current_price"] = price

            await broadcast({
                "type": "update",
                "prices": prices,
                "ema": ema_data,
                "open_trades": open_trades,
                "closed_trades": closed_trades,
                "balance": round(balance, 2),
                "initial_balance": INITIAL_BALANCE,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

# ─── App FastAPI ───────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Avvia bot in thread separato
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    # Avvia broadcaster asincrono
    asyncio.create_task(price_broadcaster())
    yield
    global bot_running
    bot_running = False

app = FastAPI(title="Trading Bot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "Trading Bot API attiva"}

@app.get("/api/state")
def get_state():
    open_trades = get_open_trades()
    for trade in open_trades:
        price = prices.get(trade["pair"], trade["entry_price"])
        if trade["direction"] == "BUY":
            trade["live_pnl_usd"] = round((price - trade["entry_price"]) * trade["quantity"], 4)
            trade["live_pnl_pct"] = round(((price - trade["entry_price"]) / trade["entry_price"]) * 100, 4)
        else:
            trade["live_pnl_usd"] = round((trade["entry_price"] - price) * trade["quantity"], 4)
            trade["live_pnl_pct"] = round(((trade["entry_price"] - price) / trade["entry_price"]) * 100, 4)
        trade["current_price"] = price

    return {
        "prices": prices,
        "ema": ema_data,
        "open_trades": open_trades,
        "closed_trades": get_closed_trades(),
        "balance": round(get_balance(), 2),
        "initial_balance": INITIAL_BALANCE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    print(f"[WS] Client connesso ({len(clients)} totali)")
    try:
        # Invia stato iniziale subito
        state = get_state()
        state["type"] = "update"
        await websocket.send_text(json.dumps(state))
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        clients.remove(websocket)
        print(f"[WS] Client disconnesso ({len(clients)} totali)")
