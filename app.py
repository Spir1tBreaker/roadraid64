import os
import sqlite3
from flask import Flask, request, redirect, session, render_template
import hmac
import hashlib

app = Flask(__name__)
# Секретный ключ сессии
app.secret_key = "raidroad64_secret_2025_xyz123"

# Токен бота — из Environment Variables (безопасно!)
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в Render Environment Variables!")

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def verify_telegram_data(data):
    """Проверяет подпись Telegram для GET-параметров"""
    hash = data.pop('hash', None)
    if not hash:
        return False
    # Сортируем и собираем строку проверки
    check = '\n'.join(f"{k}={v}" for k, v in sorted(data.items()) if v is not None)
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    hmac_hash = hmac.new(secret, check.encode(), 'sha256').hexdigest()
    return hmac_hash == hash

@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

# 🔥 ВАЖНО: принимаем GET, а не POST!
@app.route('/telegram-login')
def telegram_login():
    # Получаем все параметры из URL
    data = {
        'id': request.args.get('id'),
        'first_name': request.args.get('first_name'),
        'last_name': request.args.get('last_name'),
        'username': request.args.get('username'),
        'photo_url': request.args.get('photo_url'),
        'auth_date': request.args.get('auth_date'),
        'hash': request.args.get('hash')
    }

    if not verify_telegram_data(data):
        return "❌ Авторизация не удалась", 403

    username = data.get('username', f"user_{data['id']}")
    session['user'] = username

    # Сохраняем в БД
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    return redirect('/')


@app.route('/api/reports')
def get_reports():
    # ... твой код ...
    return jsonify([
        {
            "id": r[0],
            "username": r[1],
            "lat": r[2],
            "lon": r[3],
            "time_str": time_str,
            "likes": r[6] or 0,
            "gone_count": r[7] or 0
            # ❌ НЕ включай "trust_level", если его нет в SQL
        }
        for r in rows
    ])


@app.route('/api/me')
def api_me():
    if 'user' not in session:
        return {'error': 'not logged in'}, 401
    return {'username': session['user']}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)