import os
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, request, redirect, session, render_template, jsonify
import hmac
import hashlib

app = Flask(__name__)
app.secret_key = "raidroad64_secret_2025_xyz123"

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

    # Таблица голосов (создаётся при первом голосе, но создадим сразу)
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    c.execute('''
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
        # ✅ Правильный фильтр по UTC (SQLite хранит как UTC)
        cur.execute("""
            SELECT 
                r.id, r.username, r.lat, r.lon, r.timestamp,
                COALESCE(l.count, 0) as likes,
                COALESCE(g.count, 0) as gone_count
            FROM reports r
            LEFT JOIN (
                SELECT report_id, COUNT(*) as count 
                FROM votes 
                WHERE vote_type = 'like' 
                GROUP BY report_id
            ) l ON r.id = l.report_id
            LEFT JOIN (
                SELECT report_id, COUNT(*) as count 
                FROM votes 
                WHERE vote_type = 'gone' 
                GROUP BY report_id
            ) g ON r.id = g.report_id
            WHERE r.timestamp > datetime('now', '-3 hours')
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
                "timestamp": r[4],
                "likes": r[5],
                "gone_count": r[6]
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

@app.route('/api/vote', methods=['POST'])
def vote():
    if 'user' not in session:
        return jsonify({"error": "login required"}), 401

    data = request.get_json()
    report_id = data.get('report_id')
    vote_type = data.get('type')
    voter = session['user']

    if not isinstance(report_id, int) or vote_type not in ('like', 'gone'):
        return jsonify({"error": "invalid data"}), 400

    conn = sqlite3.connect('votes.db')
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter))
    if cur.fetchone():
        conn.close()
        return jsonify({"error": "already voted"}), 400

    # Проверка: не за себя ли голосует
    conn_reports = sqlite3.connect('reports.db')
    cur_reports = conn_reports.cursor()
    cur_reports.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    report = cur_reports.fetchone()
    if not report:
        conn_reports.close(); conn.close()
        return jsonify({"error": "report not found"}), 404
    if report[0] == voter:
        conn_reports.close(); conn.close()
        return jsonify({"error": "cannot vote for yourself"}), 400
    conn_reports.close()

    # Добавляем голос
    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter, vote_type))
    conn.commit()
    conn.close()

    # "Уехали" — старим метку на 10 минут
    if vote_type == 'gone':
        conn2 = sqlite3.connect('reports.db')
        cur2 = conn2.cursor()
        cur2.execute("SELECT 1 FROM reports WHERE id = ?", (report_id,))
        if cur2.fetchone():
            cur2.execute("""
                UPDATE reports 
                SET timestamp = datetime(timestamp, '-600 seconds')
                WHERE id = ?
            """, (report_id,))
            conn2.commit()
        conn2.close()

    return jsonify({"status": "voted"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)