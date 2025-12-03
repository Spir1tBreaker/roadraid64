import os
import sqlite3
import hashlib
import hmac
from urllib.parse import parse_qsl
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session, redirect
from database import init_db, ensure_user, get_user, create_report, get_recent_reports, delete_report, vote, get_leaderboard

app = Flask(__name__)
app.secret_key = os.environ.get('raidroad64_secret_2025_xyz123', 'raidroad64_secret_2025')

# Получаем токен бота из переменной окружения (обязательно на Render)
TELEGRAM_BOT_TOKEN = os.environ.get('8275605736:AAHaRaLoJU3PQOcTA70exfTBN_o5BoB0E34')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("8275605736:AAHaRaLoJU3PQOcTA70exfTBN_o5BoB0E34")

def init_db():
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            report_id INTEGER,
            voter_username TEXT,
            vote_type TEXT CHECK(vote_type IN ('like', 'gone')),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
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
def telegram_login():
    data = dict(parse_qsl(request.get_data(as_text=True)))
    if not verify_telegram_data(data):
        return "Invalid signature", 403

    user_id = int(data['id'])
    username = data.get('username', f'user{user_id}')
    first_name = data.get('first_name', '')

    # Сохраняем/обновляем пользователя
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

    session['username'] = username
    return redirect('/')

# === API ===
@app.route('/api/user')
def user_info():
    if 'username' not in session:
        return jsonify({"error": "not logged in"}), 401
    username = session['username']
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("SELECT trust_level FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    trust_level = row[0] if row else 1
    conn.close()
    return jsonify({"username": username, "trust_level": trust_level})

@app.route('/api/reports')
def get_reports():
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.username, r.lat, r.lon, r.timestamp,
               u.trust_level,
               (SELECT COUNT(*) FROM votes WHERE report_id = r.id AND vote_type = 'like') as likes,
               (SELECT COUNT(*) FROM votes WHERE report_id = r.id AND vote_type = 'gone') as gone_count
        FROM reports r
        LEFT JOIN users u ON r.username = u.username
        WHERE r.timestamp > datetime('now', 'utc', '-2 hours')
    """)
    rows = cur.fetchall()
    conn.close()

    from datetime import timedelta
    saratov_tz = timezone(timedelta(hours=4))
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
        local_time = utc_time.astimezone(saratov_tz)
        time_str = local_time.strftime("%H:%M")

        reports.append({
            "id": r[0],
            "username": r[1],
            "lat": r[2],
            "lon": r[3],
            "time_str": time_str,
            "trust_level": r[5] or 1,
            "likes": r[6] or 0,
            "gone_count": r[7] or 0
        })
    return jsonify(reports)

@app.route('/api/report', methods=['POST'])
def add_report():
    if 'username' not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json()
    username = session['username']
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
    if 'username' not in session:
        return jsonify({"error": "login required"}), 401
    username = session['username']
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    if not row or row[0] != username:
        conn.close()
        return jsonify({"error": "not your report"}), 403
    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    cur.execute("DELETE FROM votes WHERE report_id = ?", (report_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route('/api/vote', methods=['POST'])
def vote():
    if 'username' not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json()
    report_id = data['report_id']
    vote_type = data['type']
    voter = session['username']
    if vote_type not in ('like', 'gone'):
        return jsonify({"error": "invalid type"}), 400
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    author = cur.fetchone()
    if not author or author[0] == voter:
        conn.close()
        return jsonify({"error": "cannot vote for yourself"}), 400
    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter))
    if cur.fetchone():
        conn.close()
        return jsonify({"error": "already voted"}), 400
    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter, vote_type))
    conn.commit()
    conn.close()
    return jsonify({"status": "voted"})

# === Запуск сервера ===
if __name__ == '__main__':
    # Для локального запуска (не используется на Render)
    app.run(host='0.0.0.0', port=5000, debug=True)
else:
    # Render будет запускать через gunicorn, но на всякий случай:
    pass