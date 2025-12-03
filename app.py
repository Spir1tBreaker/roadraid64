import os
import sqlite3
from flask import Flask, request, redirect, session, render_template
from urllib.parse import parse_qsl
import hashlib
import hmac

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'raidroad64-dev-secret')

# Токен бота — обязателен на Render
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан! Добавьте в Environment Variables.")

# Инициализация базы
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

# Проверка подписи Telegram
def verify(data):
    hash = data.pop('hash', None)
    if not hash:
        return False
    check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    hmac_hash = hmac.new(secret, check.encode(), 'sha256').hexdigest()
    return hmac_hash == hash

# Главная страница
@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html', username=session['user'])

# Страница входа
@app.route('/login')
def login():
    return render_template('login.html')

# Обработка входа (POST от Telegram)
@app.route('/telegram-login', methods=['POST'])
def telegram_login():
    data = dict(parse_qsl(request.get_data(as_text=True)))
    if not verify(data):
        return "Invalid auth", 403

    username = data.get('username', f"user{data['id']}")
    session['user'] = username

    # Сохраняем в базу
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    return redirect('/')

# Простой API для теста
@app.route('/api/user')
def api_user():
    return {'user': session.get('user')}

# Запуск
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)