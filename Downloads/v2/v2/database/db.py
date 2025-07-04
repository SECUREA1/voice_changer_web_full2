import os
import sqlite3

# Directory for database file
ENV_DB_PATH = os.getenv('APP_DB_PATH')
if ENV_DB_PATH:
    DB_PATH = ENV_DB_PATH
    DB_DIR = os.path.dirname(DB_PATH)
else:
    DB_DIR = os.path.dirname(__file__)
    DB_PATH = os.path.join(DB_DIR, 'admin.db')

# SQL statements to create tables
TABLES_SQL = [
    '''CREATE TABLE IF NOT EXISTS users (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           username TEXT UNIQUE,
           password TEXT,
           wallet TEXT UNIQUE
       );''',
    '''CREATE TABLE IF NOT EXISTS collections (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT
       );''',
    '''CREATE TABLE IF NOT EXISTS archetypes (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT,
           collection_id INTEGER
       );''',
    '''CREATE TABLE IF NOT EXISTS tokens (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT,
           archetype_id INTEGER
       );''',
    '''CREATE TABLE IF NOT EXISTS marketplace_items (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           title TEXT,
           description TEXT,
           wallet TEXT,
           filename TEXT,
           chain TEXT,
           token TEXT,
           type TEXT,
           price TEXT
       );''',
    '''CREATE TABLE IF NOT EXISTS leaderboard (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           wallet TEXT,
           chain TEXT,
           rewards INTEGER DEFAULT 0
       );'''
  ,'''CREATE TABLE IF NOT EXISTS login_events (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER,
           wallet TEXT,
           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
       );'''
  ,'''CREATE TABLE IF NOT EXISTS settings (
           key TEXT PRIMARY KEY,
           value TEXT
       );'''
  ,'''CREATE TABLE IF NOT EXISTS chat_messages (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           user TEXT,
           message TEXT,
           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
       );'''
  ,'''CREATE TABLE IF NOT EXISTS user_audio (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           wallet TEXT,
           username TEXT,
           filename TEXT,
           source TEXT,
           created DATETIME DEFAULT CURRENT_TIMESTAMP
       );'''
]

def init_db():
    """
    Ensure the database directory and file exist, and create all tables.
    """
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for sql in TABLES_SQL:
        c.execute(sql)
    # add wallet column if missing
    c.execute('PRAGMA table_info(users)')
    cols = [r[1] for r in c.fetchall()]
    if 'wallet' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN wallet TEXT UNIQUE')
    # insert default settings if missing
    defaults = [
        ('api_enabled', '1'),
        ('contracts_enabled', '1'),
        ('policy_level', 'standard')
    ]
    for k, v in defaults:
        c.execute("SELECT 1 FROM settings WHERE key=?", (k,))
        if not c.fetchone():
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
    # insert default user if not exists
    c.execute("SELECT 1 FROM users WHERE username = 'chaines' LIMIT 1;")
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (username, password, wallet) VALUES (?, ?, ?)",
            ('chaines', 'winner', None)
        )
    conn.commit()
    conn.close()


def connect_db():
    """
    Return a new connection to the database.
    """
    # You can set row_factory or PRAGMA here if needed
    return sqlite3.connect(DB_PATH)


def verify_user_wallet(username: str, wallet: str) -> bool:
    """Return True if the given username is linked to the wallet."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM users WHERE username=? AND wallet=?",
            (username, wallet),
        )
        return c.fetchone() is not None


def get_wallet_rewards(wallet: str, chain: str | None = None) -> int:
    """Fetch total rewards for a wallet, optionally filtered by chain."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if chain:
            c.execute(
                "SELECT rewards FROM leaderboard WHERE wallet=? AND chain=?",
                (wallet, chain),
            )
            row = c.fetchone()
            return int(row[0]) if row else 0
        c.execute(
            "SELECT SUM(rewards) FROM leaderboard WHERE wallet=?",
            (wallet,),
        )
        row = c.fetchone()
        return int(row[0]) if row and row[0] else 0


def add_user_audio(wallet: str | None, username: str | None,
                   filename: str, source: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO user_audio (wallet, username, filename, source)
            VALUES (?, ?, ?, ?)""",
            (wallet, username, filename, source),
        )
        conn.commit()


def get_user_audio(*, wallet: str | None = None, username: str | None = None):
    if not wallet and not username:
        return []
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if wallet:
            c.execute(
                "SELECT id, wallet, username, filename, source, created"
                " FROM user_audio WHERE wallet=? ORDER BY id DESC",
                (wallet,),
            )
        else:
            c.execute(
                "SELECT id, wallet, username, filename, source, created"
                " FROM user_audio WHERE username=? ORDER BY id DESC",
                (username,),
            )
        rows = c.fetchall()
    return [
        {
            "id": r[0],
            "wallet": r[1],
            "username": r[2],
            "filename": r[3],
            "source": r[4],
            "created": r[5],
        }
        for r in rows
    ]
