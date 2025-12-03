import os
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, request, redirect, session, render_template, jsonify
import hmac
import hashlib

app = Flask(__name__)
app.secret_key = "raidroad64_secret_2025_xyz123"

# Токен бота из Render Environment Variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в Render Environment Variables!")


def init_db():
    # База пользователей
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

    # База меток
    conn = sqlite3.connect('reports.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


init_db()


def verify_telegram_data(data):
    hash = data.pop('hash', None)
    if not hash:
        return False
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


@app.route('/telegram-login')
def telegram_login():
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

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    return redirect('/')


@app.route('/api/me')
def api_me():
    if 'user' not in session:
        return {'error': 'not logged in'}, 401
    return {'username': session['user']}


@app.route('/api/reports')
def get_reports():
    try:
        conn = sqlite3.connect('reports.db')
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, lat, lon, timestamp
            FROM reports
            WHERE timestamp > datetime('now', 'utc', '-2 hours')
        """)
        rows = cur.fetchall()
        conn.close()

        reports = []
        for r in rows:
            ts = r[4]
            if '.' in ts:
                ts = ts.split('.')[0]
            if 'Z' not in ts and '+' not in ts:
                ts += '+00:00'
            utc_time = datetime.fromisoformat(ts)
            if utc_time.tzinfo is None:
                utc_time = utc_time.replace(tzinfo=timezone.utc)
            local_time = utc_time.astimezone(timezone(timedelta(hours=4)))
            time_str = local_time.strftime("%H:%M")

            reports.append({
                "id": r[0],
                "username": r[1],
                "lat": r[2],
                "lon": r[3],
                "time_str": time_str,
                "likes": 0,
                "gone_count": 0
            })
        return jsonify(reports)
    except Exception as e:
        print("Ошибка в /api/reports:", e)
        return jsonify([])


@app.route('/api/report', methods=['POST'])
def add_report():
    if 'user' not in session:
        return jsonify({"error": "login required"}), 401

    data = request.get_json()
    username = session['user']
    lat = data['lat']
    lon = data['lon']

    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("INSERT INTO reports (username, lat, lon, timestamp) VALUES (?, ?, ?, ?)",
                (username, lat, lon, now_utc))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route('/api/report/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    if 'user' not in session:
        return jsonify({"error": "login required"}), 401

    username = session['user']
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    if not row or row[0] != username:
        conn.close()
        return jsonify({"error": "not your report"}), 403

    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# Не реализовано (заглушка)
@app.route('/api/vote', methods=['POST'])
def vote():
    return jsonify({"error": "not implemented"}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)