import os
import sqlite3
from flask import Flask, request, redirect, session, render_template
from urllib.parse import parse_qsl
import hashlib
import hmac

app = Flask(__name__)
app.secret_key = "raidroad64_secret_2025_xyz123"

# Обязательно: токен из Render Environment
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN не задан в Environment Variables!")


# Инициализация базы (только пользователи)
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


# Главная страница — только для авторизованных
@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html')


# Страница входа
@app.route('/login')
def login():
    return render_template('login.html')


# Telegram Login — ОДИН единственный POST-эндпоинт
@app.route('/telegram-login', methods=['POST'])
def telegram_login():
    # Получаем данные как строку
    data = dict(parse_qsl(request.get_data(as_text=True)))

    # Проверка подписи
    received_hash = data.pop('hash', None)
    if not received_hash:
        return "No hash", 400

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), 'sha256').hexdigest()

    if computed_hash != received_hash:
        return "Invalid auth", 403

    # Получаем username или создаём заглушку
    username = data.get('username', f"user_{data['id']}")
    session['user'] = username

    # Сохраняем в БД
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    # Перенаправляем на карту
    return redirect('/')


# Простой API для проверки сессии (для JS)
@app.route('/api/me')
def api_me():
    return {'username': session.get('user')}


# === ЗАПУСК НА RENDER ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)