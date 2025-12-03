import os
import sqlite3
import hashlib
import hmac
from urllib.parse import parse_qsl
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session, redirect

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'raidroad64_secret_2025')

# Получаем токен бота из переменной окружения
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN не задан! Добавьте его в Environment Variables на Render.")

def init_db():
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            report_id INTEGER,
            voter_username TEXT,
            vote_type TEXT CHECK(vote_type IN ('like', 'gone')),
            PRIMARY KEY (report_id, voter_username)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def verify_telegram_data(data):
    received_hash = data.get('hash')
    if not received_hash:
        return False
    check_data = {k: v for k, v in data.items() if k != 'hash'}
    check_list = sorted([f"{k}={v}" for k, v in check_data.items()])
    check_string = "\n".join(check_list)
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    hmac_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return hmac_hash == received_hash

@app.route('/')
def index():
    if 'username' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/login/telegram', methods=['POST'])
@app.route('/login/telegram', methods=['POST'])
def telegram_login():
    data = dict(parse_qsl(request.get_data(as_text=True)))

    # Проверка подписи
    if not verify_telegram_data(data):
        return "❌ Подделка данных запрещена", 403

    # Извлекаем данные
    user_id = data['id']
    username = data.get('username', f'user{user_id}')

    # Сохраняем в БД
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    # Авторизуем
    session['username'] = username
    return redirect('/')

# === API-эндпоинты (оставь как есть из твоей версии 1.0) ===
# ... (все твои существующие маршруты: /api/user, /api/reports, /api/report, /api/vote ...) 

# Для краткости здесь не привожу их — просто оставь свои рабочие функции!

# === Запуск на Render ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)