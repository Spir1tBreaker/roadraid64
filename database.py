import sqlite3
from datetime import datetime, timezone

DB_PATH = 'reports.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
            PRIMARY KEY (report_id, voter_username),
            FOREIGN KEY(voter_username) REFERENCES users(username)
        )
    ''')

    conn.commit()
    conn.close()


def ensure_user(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, trust_level FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def create_report(username, lat, lon):
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO reports (username, lat, lon, timestamp) VALUES (?, ?, ?, ?)",
                (username, lat, lon, now_utc))
    conn.commit()
    conn.close()


def get_recent_reports(hours=2):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            r.id, r.username, r.lat, r.lon, r.timestamp,
            u.trust_level,
            COALESCE(likes.cnt, 0) as likes,
            COALESCE(gone.cnt, 0) as gone_count
        FROM reports r
        JOIN users u ON r.username = u.username
        LEFT JOIN (SELECT report_id, COUNT(*) as cnt FROM votes WHERE vote_type = 'like' GROUP BY report_id) likes
            ON r.id = likes.report_id
        LEFT JOIN (SELECT report_id, COUNT(*) as cnt FROM votes WHERE vote_type = 'gone' GROUP BY report_id) gone
            ON r.id = gone.report_id
        WHERE r.timestamp > datetime('now', 'utc', '-{} hours')
    """.format(hours))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_report(report_id, username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    if not row or row[0] != username:
        conn.close()
        return False
    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    cur.execute("DELETE FROM votes WHERE report_id = ?", (report_id,))
    conn.commit()
    conn.close()
    return True


def update_trust_level(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) 
        FROM reports r
        JOIN votes v ON r.id = v.report_id 
        WHERE r.username = ? AND v.vote_type = 'like'
    """, (username,))
    total_likes = cur.fetchone()[0]

    if total_likes >= 50:
        level = 5
    elif total_likes >= 25:
        level = 4
    elif total_likes >= 10:
        level = 3
    elif total_likes >= 5:
        level = 2
    else:
        level = 1

    cur.execute("UPDATE users SET trust_level = ? WHERE username = ?", (level, username))
    conn.commit()
    conn.close()
    return level


def vote(report_id, voter_username, vote_type):
    if vote_type not in ('like', 'gone'):
        return False

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    report = cur.fetchone()
    if not report:
        conn.close()
        return False
    author = report[0]
    if voter_username == author:
        conn.close()
        return False

    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter_username))
    if cur.fetchone():
        conn.close()
        return False

    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter_username, vote_type))
    conn.commit()
    conn.close()

    if vote_type == 'like':
        update_trust_level(author)

    return True


def get_leaderboard(limit=10):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            r.username,
            u.trust_level,
            COUNT(v.report_id) as total_likes
        FROM reports r
        JOIN votes v ON r.id = v.report_id AND v.vote_type = 'like'
        JOIN users u ON r.username = u.username
        GROUP BY r.username
        ORDER BY total_likes DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]