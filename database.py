import sqlite3
from datetime import datetime, timezone

DB_PATH = 'reports.db'


def get_db():
    """Возвращает подключение к базе данных с поддержкой dict-доступа."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # позволяет делать r['id'] вместо r[0]
    return conn


def init_db():
    """Инициализирует все таблицы при старте приложения."""
    conn = get_db()
    cur = conn.cursor()

    # Пользователи (авторизованные через Telegram)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            trust_level INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Метки ДПС
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
        )
    ''')

    # Голоса: лайки и «уехали»
    cur.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            report_id INTEGER NOT NULL,
            voter_username TEXT NOT NULL,
            vote_type TEXT CHECK(vote_type IN ('like', 'gone')),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (report_id, voter_username),
            FOREIGN KEY(voter_username) REFERENCES users(username) ON DELETE CASCADE,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()


# === Пользователи ===
def ensure_user(username):
    """Создаёт пользователя, если его ещё нет."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()


def get_user(username):
    """Получает данные пользователя по имени (никнейму из Telegram)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, trust_level FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_trust_level_by_likes(username):
    """Обновляет trust_level на основе количества лайков у пользователя."""
    conn = get_db()
    cur = conn.cursor()

    # Считаем общее число лайков под метками пользователя
    cur.execute("""
        SELECT COUNT(*)
        FROM reports r
        JOIN votes v ON r.id = v.report_id
        WHERE r.username = ? AND v.vote_type = 'like'
    """, (username,))
    total_likes = cur.fetchone()[0]

    # Простая геймификация: уровень = лайки // 5 (макс. 5)
    level = min(5, max(1, total_likes // 5 + 1))

    cur.execute("UPDATE users SET trust_level = ? WHERE username = ?", (level, username))
    conn.commit()
    conn.close()
    return level


# === Метки (reports) ===
def create_report(username, lat, lon):
    """Создаёт новую метку ДПС."""
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (username, lat, lon, timestamp)
        VALUES (?, ?, ?, ?)
    """, (username, lat, lon, now_utc))
    report_id = cur.lastrowid
    conn.commit()
    conn.close()
    return report_id


def get_recent_reports(hours=2):
    """Возвращает все метки за последние N часов с агрегацией лайков/«уехали»."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            r.id, r.username, r.lat, r.lon, r.timestamp,
            u.trust_level,
            COALESCE(likes.cnt, 0) AS likes,
            COALESCE(gone.cnt, 0) AS gone_count
        FROM reports r
        JOIN users u ON r.username = u.username
        LEFT JOIN (
            SELECT report_id, COUNT(*) AS cnt 
            FROM votes 
            WHERE vote_type = 'like' 
            GROUP BY report_id
        ) likes ON r.id = likes.report_id
        LEFT JOIN (
            SELECT report_id, COUNT(*) AS cnt 
            FROM votes 
            WHERE vote_type = 'gone' 
            GROUP BY report_id
        ) gone ON r.id = gone.report_id
        WHERE r.timestamp > datetime('now', 'utc', '-{} hours')
        ORDER BY r.timestamp DESC
    """.format(hours))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_report(report_id, username):
    """Удаляет метку, если она принадлежит пользователю."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    if not row or row[0] != username:
        conn.close()
        return False
    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    # CASCADE удалит и связанные голоса, но на всякий случай:
    cur.execute("DELETE FROM votes WHERE report_id = ?", (report_id,))
    conn.commit()
    conn.close()
    return True


# === Голоса (votes) ===
def vote(report_id, voter_username, vote_type):
    """Добавляет голос (like/gone), если пользователь ещё не голосовал и не за себя."""
    if vote_type not in ('like', 'gone'):
        return False

    conn = get_db()
    cur = conn.cursor()

    # Проверяем, что метка существует и не принадлежит голосующему
    cur.execute("SELECT username FROM reports WHERE id = ?", (report_id,))
    report = cur.fetchone()
    if not report:
        conn.close()
        return False
    if report[0] == voter_username:
        conn.close()
        return False  # нельзя голосовать за себя

    # Проверяем, не голосовал ли уже
    cur.execute("SELECT 1 FROM votes WHERE report_id = ? AND voter_username = ?", (report_id, voter_username))
    if cur.fetchone():
        conn.close()
        return False

    # Добавляем голос
    cur.execute("INSERT INTO votes (report_id, voter_username, vote_type) VALUES (?, ?, ?)",
                (report_id, voter_username, vote_type))
    conn.commit()
    conn.close()

    # Обновляем уровень автора метки (только для лайков)
    if vote_type == 'like':
        update_trust_level_by_likes(report[0])

    return True


# === Лидерборд ===
def get_leaderboard(limit=20):
    """Возвращает топ пользователей по количеству полученных лайков."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            r.username,
            u.trust_level,
            COUNT(v.report_id) AS total_likes
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