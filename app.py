<<<<<<< HEAD
from flask import Flask, request, jsonify, render_template, session, redirect
import sqlite3
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
app.secret_key = 'raidroad64_secret_2025'


def init_db():
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()

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
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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


# Автоматически создаём пользователя при первом входе
def ensure_user(username):
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        if 2 <= len(username) <= 30:
            session['username'] = username
            ensure_user(username)  # гарантируем, что пользователь в базе
            return redirect('/')
        else:
            return "Имя должно быть от 2 до 30 символов", 400
    return render_template('login.html')


@app.route('/')
def index():
    if 'username' not in session:
        return redirect('/login')
    return render_template('index.html')


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

    # Получаем отчёты за последние 2 часа по UTC
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

    saratov_tz = timezone(timedelta(hours=4))
    reports = []
    for r in rows:
        if not r[4]:
            continue

        # Если timestamp уже в UTC (как мы сохраняем), парсим как UTC
        try:
            # Убираем возможные микросекунды и Z
            ts_str = r[4]
            if '.' in ts_str:
                ts_str = ts_str.split('.')[0]
            if 'Z' in ts_str:
                ts_str = ts_str.replace('Z', '+00:00')
            elif '+' not in ts_str and '-' not in ts_str[10:]:
                # Если нет указания часового пояса — считаем UTC
                ts_str += '+00:00'

            utc_time = datetime.fromisoformat(ts_str)
            if utc_time.tzinfo is None:
                utc_time = utc_time.replace(tzinfo=timezone.utc)

            local_time = utc_time.astimezone(saratov_tz)
            time_str = local_time.strftime("%H:%M")
        except Exception as e:
            # На случай ошибки — показываем как есть
            time_str = r[4].split(' ')[1][:5] if ' ' in r[4] else '00:00'

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

    # Просто ISO-формат UTC без микросекунд
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
    cur.execute("DELETE FROM votes WHERE report_id = ?", (report_id,))  # удаляем и голоса
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ==== НОВОЕ: голосование ====
@app.route('/api/vote', methods=['POST'])
def vote():
    if 'username' not in session:
        return jsonify({"error": "login required"}), 401

    data = request.get_json()
    report_id = data['report_id']
    vote_type = data['type']  # 'like' или 'gone'
    voter = session['username']

    if vote_type not in ('like', 'gone'):
        return jsonify({"error": "invalid type"}), 400

    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()

    # Проверяем, не голосовал ли уже
    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter))
    if cur.fetchone():
        conn.close()
        return jsonify({"error": "already voted"}), 400

    # Добавляем голос
    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter, vote_type))
    conn.commit()
    conn.close()
    return jsonify({"status": "voted"})


if __name__ == '__main__':
=======
from flask import Flask, request, jsonify, render_template, session, redirect
import sqlite3
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
app.secret_key = 'raidroad64_secret_2025'


def init_db():
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()

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
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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


# Автоматически создаём пользователя при первом входе
def ensure_user(username):
    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        if 2 <= len(username) <= 30:
            session['username'] = username
            ensure_user(username)  # гарантируем, что пользователь в базе
            return redirect('/')
        else:
            return "Имя должно быть от 2 до 30 символов", 400
    return render_template('login.html')


@app.route('/')
def index():
    if 'username' not in session:
        return redirect('/login')
    return render_template('index.html')


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

    # Получаем отчёты за последние 2 часа по UTC
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

    saratov_tz = timezone(timedelta(hours=4))
    reports = []
    for r in rows:
        if not r[4]:
            continue

        # Если timestamp уже в UTC (как мы сохраняем), парсим как UTC
        try:
            # Убираем возможные микросекунды и Z
            ts_str = r[4]
            if '.' in ts_str:
                ts_str = ts_str.split('.')[0]
            if 'Z' in ts_str:
                ts_str = ts_str.replace('Z', '+00:00')
            elif '+' not in ts_str and '-' not in ts_str[10:]:
                # Если нет указания часового пояса — считаем UTC
                ts_str += '+00:00'

            utc_time = datetime.fromisoformat(ts_str)
            if utc_time.tzinfo is None:
                utc_time = utc_time.replace(tzinfo=timezone.utc)

            local_time = utc_time.astimezone(saratov_tz)
            time_str = local_time.strftime("%H:%M")
        except Exception as e:
            # На случай ошибки — показываем как есть
            time_str = r[4].split(' ')[1][:5] if ' ' in r[4] else '00:00'

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

    # Просто ISO-формат UTC без микросекунд
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
    cur.execute("DELETE FROM votes WHERE report_id = ?", (report_id,))  # удаляем и голоса
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ==== НОВОЕ: голосование ====
@app.route('/api/vote', methods=['POST'])
def vote():
    if 'username' not in session:
        return jsonify({"error": "login required"}), 401

    data = request.get_json()
    report_id = data['report_id']
    vote_type = data['type']  # 'like' или 'gone'
    voter = session['username']

    if vote_type not in ('like', 'gone'):
        return jsonify({"error": "invalid type"}), 400

    conn = sqlite3.connect('reports.db')
    cur = conn.cursor()

    # Проверяем, не голосовал ли уже
    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter))
    if cur.fetchone():
        conn.close()
        return jsonify({"error": "already voted"}), 400

    # Добавляем голос
    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter, vote_type))
    conn.commit()
    conn.close()
    return jsonify({"status": "voted"})


if __name__ == '__main__':
>>>>>>> 14f06cc (V1.01)
    app.run(debug=True)