# db.py
import os
import sqlite3
from werkzeug.security import generate_password_hash

# path to your database file
# allow override via env var so the DB can live on a persistent volume
ENV_DB_PATH = os.getenv("APP_DB_PATH")
if ENV_DB_PATH:
    DB_PATH = ENV_DB_PATH
    DB_DIR = os.path.dirname(DB_PATH)
else:
    BASE_DIR = os.path.dirname(__file__)
    DB_DIR = os.path.join(BASE_DIR, "database")
    DB_PATH = os.path.join(DB_DIR, "admin.db")

def init_db():
    # make sure the folder exists
    os.makedirs(DB_DIR, exist_ok=True)

    # connect & create tables
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
          id       INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT,
          password TEXT,
          wallet   TEXT UNIQUE
        )
    ''')
    c.execute('PRAGMA table_info(users)')
    cols = [r[1] for r in c.fetchall()]
    if 'wallet' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN wallet TEXT UNIQUE')
    c.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_users_wallet_username '
        'ON users(wallet, username)'
    )
    c.execute('''
        CREATE TABLE IF NOT EXISTS collections (
          id   INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS archetypes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          collection_id INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          archetype_id INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_events (
          id       INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id  INTEGER,
          wallet   TEXT,
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_audio (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          wallet TEXT,
          username TEXT,
          filename TEXT,
          source TEXT,
          created DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS tip_wallets (
          token TEXT PRIMARY KEY,
          address TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pool_payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          wallet TEXT,
          chain TEXT,
          token TEXT,
          amount TEXT,
          tx_hash TEXT,
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user TEXT,
          message TEXT,
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          wallet TEXT,
          chain TEXT,
          rewards INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS marketplace_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            wallet TEXT,
            filename TEXT,
            chain TEXT,
            token TEXT,
            type TEXT,
            price TEXT,
            minted INTEGER DEFAULT 0
        )
    ''')
    c.execute('PRAGMA table_info(marketplace_items)')
    cols = [r[1] for r in c.fetchall()]
    if 'description' not in cols:
        c.execute('ALTER TABLE marketplace_items ADD COLUMN description TEXT')
    if 'token' not in cols:
        c.execute('ALTER TABLE marketplace_items ADD COLUMN token TEXT DEFAULT "USDT"')
    if 'minted' not in cols:
        c.execute('ALTER TABLE marketplace_items ADD COLUMN minted INTEGER DEFAULT 0')
    c.execute('SELECT COUNT(*) FROM tip_wallets')
    if c.fetchone()[0] == 0:
        defaults = [
            ('BTC', 'btc-admin-wallet'),
            ('ETH', 'eth-admin-wallet'),
            ('BNB', 'bnb-admin-wallet'),
            ('SOL', 'sol-admin-wallet'),
            ('ADA', 'ada-admin-wallet')
        ]
        c.executemany(
            'INSERT INTO tip_wallets (token, address) VALUES (?, ?)', defaults
        )
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT
    )''')
    defaults = [
        ('api_enabled', '1'),
        ('contracts_enabled', '1'),
        ('policy_level', 'standard')
    ]
    for k, v in defaults:
        if not c.execute('SELECT 1 FROM settings WHERE key=?', (k,)).fetchone():
            c.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (k, v))
    # …and so on for archetypes, tokens, marketplace_items, leaderboard, etc.

    # insert default admin user if missing
    if not c.execute("SELECT 1 FROM users WHERE username='chaines'").fetchone():
        hashed = generate_password_hash("winner")
        c.execute(
          "INSERT INTO users (username, password, wallet) VALUES (?, ?, ?)",
          ("chaines", hashed, None)
        )

    conn.commit()
    conn.close()

def connect_db():
    """return a new sqlite3 connection"""
    return sqlite3.connect(DB_PATH)


def add_user_audio(wallet: str | None, username: str | None,
                   filename: str, source: str) -> None:
    """Record an uploaded audio file for later retrieval."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_audio (wallet, username, filename, source)
            VALUES (?, ?, ?, ?)
            """,
            (wallet, username, filename, source),
        )
        conn.commit()


def get_user_audio(*, wallet: str | None = None, username: str | None = None):
    """Fetch stored audio uploads for a wallet or username."""
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
