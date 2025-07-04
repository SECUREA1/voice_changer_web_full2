import os
import sqlite3
import ssl
import sys

# Eventlet expects `ssl.wrap_socket`, which was removed in Python 3.12.
# Provide a basic shim before importing eventlet or any libraries that rely on it.
if not hasattr(ssl, "wrap_socket"):
    ssl.wrap_socket = ssl.SSLContext(ssl.PROTOCOL_TLS).wrap_socket

from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, send_from_directory, session
)
from flask_cors import CORS
from flask_login import (
    LoginManager, UserMixin,
    login_user, login_required, logout_user, current_user
)
from flask_socketio import SocketIO, emit, join_room
from pkg_resources import get_distribution, parse_version
from rpc_health import check_all as rpc_check_all
from datetime import timedelta, datetime
from functools import wraps
import eventlet
from web3 import Web3
import requests
import uuid
import socket
from pydub import AudioSegment
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import base64
from blockchain import mint_nft as mint_on_chain
from db import DB_PATH, add_user_audio, get_user_audio

def _verify_socketio_versions():
    flask_sock = get_distribution("flask-socketio").version
    py_sock = get_distribution("python-socketio").version
    if parse_version(flask_sock) < parse_version("5.3.6") or parse_version(py_sock) < parse_version("5.7.0"):
        raise RuntimeError(
            "Incompatible Socket.IO library versions:\n"
            f"flask-socketio {flask_sock}, python-socketio {py_sock}.\n"
            "Upgrade with: pip install 'flask-socketio>=5.3.6' 'python-socketio>=5.7.0'"
        )

_verify_socketio_versions()

# ── 1) App & Extensions ─────────────────────────────────────────────────────────
app = Flask(__name__, static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "dev_key")
CORS(app)

# Eventlet is not fully compatible with Python 3.12. Use threading as a
# fallback when running on newer interpreters.
ASYNC_MODE = "eventlet"
if sys.version_info >= (3, 12):
    ASYNC_MODE = "threading"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=ASYNC_MODE,
    ping_timeout=120,
    ping_interval=30,
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
app.permanent_session_lifetime = timedelta(days=7)

@app.context_processor
def inject_session_data():
    return {
        'session_wallet': session.get('wallet'),
        'session_username': current_user.username if current_user.is_authenticated else ''
    }

# ── 2) Database Setup ───────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# DB_PATH comes from db.py and can be overridden with the APP_DB_PATH env var
DB_DIR = os.path.dirname(DB_PATH)
os.makedirs(DB_DIR, exist_ok=True)
app.config["DB_PATH"] = DB_PATH
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Admin wallet configuration
# store admin address in lowercase for consistent comparisons
ADMIN_WALLET = "0xbe3b933b149f78dceefe99c4859c10a561c9e4cf"
ADMIN_USERNAME = "chaines"
ADMIN_PASSWORD = "winner"
# Live voice streaming state
LIVE_STREAMERS = {}          # username -> sid
LIVE_STREAMER_WALLETS = {}   # username -> wallet address
LIVE_LISTENERS = {}          # username -> set of listener sids
LIVE_SPEAKERS = {}           # username -> set of speaker sids
LIVE_RECORDINGS = {}         # username -> list of binary chunks
sid_to_wallet = {}           # sid -> wallet string


def broadcast_listeners(host: str):
    """Notify listeners and host about the current listener list."""
    sids = LIVE_LISTENERS.get(host, set())
    names = [sid_to_user.get(sid, 'Anonymous') for sid in sids if sid_to_user.get(sid)]
    socketio.emit('listener_update', {'host': host, 'listeners': names}, room=f'listen_{host}')
    host_sid = LIVE_STREAMERS.get(host)
    if host_sid:
        socketio.emit('listener_update', {'host': host, 'listeners': names}, to=host_sid)
def finalize_live_recording(host: str, wallet: str | None = None, sid: str | None = None):

    """Write buffered live chunks to disk and optionally notify a client."""
    rec = LIVE_RECORDINGS.pop(host, None)
    if not rec:
        return None
    filename = f"{uuid.uuid4().hex}_live.webm"
    path = os.path.join(UPLOAD_FOLDER, filename)
    with open(path, "wb") as f:
        f.write(b"".join(rec))
    if wallet:
        add_user_audio(wallet, host, filename, "live_stream")
    if sid:
        try:
            socketio.emit(
                "recording_saved",
                {"url": f"/static/uploads/{filename}", "filename": filename},
                to=sid,
            )
        except Exception as e:
            app.logger.debug(f"Emit error: {e}")
    return filename

def safe_shutdown(sock):
    """Legacy no-op helper kept for backward compatibility."""
    return

# Active user tracking state
active_users = {}  # username -> last ping timestamp
sid_to_user = {}   # sid -> username

def get_active_users(timeout: int = 60):
    """Return list of usernames active within the given timeout."""
    now = datetime.utcnow().timestamp()
    return [u for u, t in active_users.items() if now - t <= timeout]

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                wallet TEXT
            )
        """)
        # ensure unique username/wallet pair and allow two usernames per wallet
        c.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_user_wallet_username '
            'ON users(wallet, username)'
        )
        # add wallet column if the table pre-exists without it
        c.execute('PRAGMA table_info(users)')
        cols = [r[1] for r in c.fetchall()]
        if 'wallet' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN wallet TEXT')
        c.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS archetypes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                collection_id INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                archetype_id INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT,
                chain TEXT,
                rewards INTEGER DEFAULT 0
            )
        """)
        c.execute("""
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
        """)
        c.execute('PRAGMA table_info(marketplace_items)')
        cols = [r[1] for r in c.fetchall()]
        if 'description' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN description TEXT')
        if 'token' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN token TEXT DEFAULT "USDT"')
        if 'minted' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN minted INTEGER DEFAULT 0')
        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                buyer_wallet TEXT,
                seller_wallet TEXT,
                chain TEXT,
                token TEXT,
                amount TEXT,
                tx_hash TEXT,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pool_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT,
                chain TEXT,
                token TEXT,
                amount TEXT,
                tx_hash TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_audio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT,
                username TEXT,
                filename TEXT,
                source TEXT,
                created DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        c.execute("""
            CREATE TABLE IF NOT EXISTS tip_wallets (
                token TEXT PRIMARY KEY,
                address TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS login_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                wallet TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        defaults = [
            ('api_enabled', '1'),
            ('contracts_enabled', '1'),
            ('policy_level', 'standard')
        ]
        for k, v in defaults:
            c.execute('SELECT 1 FROM settings WHERE key=?', (k,))
            if not c.fetchone():
                c.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (k, v))
        c.execute("SELECT COUNT(*) FROM tip_wallets")
        if c.fetchone()[0] == 0:
            defaults = [
                ('BTC', 'btc-admin-wallet'),
                ('ETH', 'eth-admin-wallet'),
                ('BNB', 'bnb-admin-wallet'),
                ('SOL', 'sol-admin-wallet'),
                ('ADA', 'ada-admin-wallet')
            ]
            c.executemany(
                'INSERT INTO tip_wallets (token, address) VALUES (?, ?)',
                defaults
            )
        # Seed default admin user
        c.execute("SELECT 1 FROM users WHERE username=? AND wallet=?", (ADMIN_USERNAME, ADMIN_WALLET))
        if not c.fetchone():
            hashed = generate_password_hash(ADMIN_PASSWORD)
            c.execute(
                "INSERT INTO users (username, password, wallet) VALUES (?, ?, ?)",
                (ADMIN_USERNAME, hashed, ADMIN_WALLET)
            )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
init_db()

# ── 3) Login / User Model ────────────────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE id=?", (user_id,))
        row = c.fetchone()
    return User(id=row[0], username=row[1]) if row else None

# Wrapper to ensure a logged-in user has also connected a wallet
def wallet_login_required(func):
    """Require a user login before accessing the wrapped route."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper

# ── 4) Web3 Setup ───────────────────────────────────────────────────────────────
ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "_owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "balance", "type": "uint256"}],
    "type": "function"
}]
ETH_RPC           = os.getenv("ETH_RPC",           "https://mainnet.infura.io/v3/e252a3114f6f48a6aa8376e2e5b9dbfb")
BSC_RPC           = os.getenv("BSC_RPC",           "https://bsc-rpc.publicnode.com")
ETH_TOKEN_ADDRESS = os.getenv("ETH_USDT_ADDRESS") or os.getenv(
    "ETH_TOKEN_ADDRESS",
    "0xdAC17F958D2ee523a2206206994597C13D831ec7",
)
BSC_TOKEN_ADDRESS = os.getenv("BSC_USDT_ADDRESS") or os.getenv(
    "BSC_TOKEN_ADDRESS",
    "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
)
BLOCKFROST_KEY    = os.getenv("BLOCKFROST_KEY",     "your_blockfrost_api_key")
CARDANO_API       = os.getenv("CARDANO_API",        "https://cardano-mainnet.blockfrost.io/api/v0")

eth_web3 = Web3(Web3.HTTPProvider(ETH_RPC))
bsc_web3 = Web3(Web3.HTTPProvider(BSC_RPC))

erc20_contract_eth = eth_web3.eth.contract(
    address=Web3.to_checksum_address(ETH_TOKEN_ADDRESS),
    abi=ERC20_ABI
)
erc20_contract_bsc = bsc_web3.eth.contract(
    address=Web3.to_checksum_address(BSC_TOKEN_ADDRESS),
    abi=ERC20_ABI
)

# ── 5) Blueprints ────────────────────────────────────────────────────────────────
from marketplace.routes import marketplace_bp
from token_mixer import mixer_bp
from nft import nft_bp
from quests import quest_bp
from voice_changer.routes import voice_bp

app.register_blueprint(marketplace_bp)
app.register_blueprint(mixer_bp)
app.register_blueprint(nft_bp)
app.register_blueprint(quest_bp)
app.register_blueprint(voice_bp)

# ── 6) API Endpoints ─────────────────────────────────────────────────────────────
@app.route('/api/claim', methods=['POST'])
def claim_quest():
    data   = request.json
    wallet = data.get('wallet')
    chain  = data.get('chain')
    reward = int(data.get('reward', 0))

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM leaderboard WHERE wallet=? AND chain=?", (wallet, chain))
        if c.fetchone():
            c.execute(
                "UPDATE leaderboard SET rewards = rewards + ? WHERE wallet=? AND chain=?",
                (reward, wallet, chain)
            )
        else:
            c.execute(
                "INSERT INTO leaderboard (wallet, chain, rewards) VALUES (?, ?, ?)",
                (wallet, chain, reward)
            )
        conn.commit()
    return jsonify(status="Success", message="Reward recorded.")

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT wallet, chain, rewards FROM leaderboard ORDER BY rewards DESC LIMIT 10")
        rows = c.fetchall()
    return jsonify([{"wallet": w, "chain": ch, "rewards": r} for w, ch, r in rows])


@app.route('/api/user-audio', methods=['GET'])
@login_required
def get_user_audio_api():
    wallet = session.get('wallet')
    if not wallet:
        return jsonify(status='error', message='No wallet connected'), 400
    uploads = get_user_audio(wallet=wallet)
    for u in uploads:
        u['url'] = f"/static/uploads/{u['filename']}" if not u['filename'].startswith('mixed/') else f"/static/{u['filename']}"
    return jsonify(uploads)

@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    data = request.json
    wallet = data.get("walletAddress")
    chain = data.get("chain")
    req  = float(data.get("requiredTokens", 1))
    try:
        if chain == 'ethereum':
            bal = erc20_contract_eth.functions.balanceOf(wallet).call()
            balance = eth_web3.fromWei(bal, 'ether')
        elif chain == 'bsc':
            bal = erc20_contract_bsc.functions.balanceOf(wallet).call()
            balance = bsc_web3.fromWei(bal, 'ether')
        elif chain == 'cardano':
            resp = requests.get(
                f"{CARDANO_API}/addresses/{wallet}",
                headers={"project_id": BLOCKFROST_KEY}
            ); resp.raise_for_status()
            amt = resp.json().get("amount", [])
            balance = next((float(a['quantity'])/1e6 for a in amt if a["unit"]=="lovelace"), 0)
        else:
            return jsonify(status="Error", message="Unsupported chain"), 400

        if balance < req:
            return jsonify(status="Error", balance=float(balance), message="Insufficient tokens"), 403

        return jsonify(status="Success", balance=float(balance), message="Access granted")

    except Exception as e:
        return jsonify(status="Error", message=str(e)), 500


@app.route('/api/rpc-health', methods=['GET'])
def rpc_health():
    """Return connectivity status for all configured RPC endpoints."""
    return jsonify(rpc_check_all())


@app.route('/api/mint-nft', methods=['POST'])
def mint_nft():
    """Receive audio pieces or a mixed file and store as minted asset."""
    title = request.form.get('title', 'New NFT')
    wallet = request.form.get('walletAddress') or request.form.get('wallet')
    chain = (request.form.get('chain') or 'ethereum').lower()

    file = (
        request.files.get('mix') or
        request.files.get('audio') or
        request.files.get('voice')
    )

    # If individual tracks provided, mix them using pydub
    if not file:
        segments = []
        for key in ('voice', 'beat', 'fx'):
            f = request.files.get(key)
            if f:
                segments.append(AudioSegment.from_file(f))
        if not segments:
            return jsonify(success=False, status='error', message='No audio uploaded'), 400
        mix = segments[0]
        for seg in segments[1:]:
            mix = mix.overlay(seg)
        filename = f"{uuid.uuid4().hex}_mix.mp3"
        path = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
        mix.export(path, format='mp3')
    else:
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)

    # record in DB for marketplace browsing
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO marketplace_items (title, wallet, filename, chain, type, price, minted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (title, wallet or '', filename, chain, 'audio', '0')
        )
        item_id = c.lastrowid
        conn.commit()

    source = 'voice_changer'
    if request.files.get('mix') or request.files.get('beat') or request.files.get('fx'):
        source = 'token_mixer'
    add_user_audio(
        wallet,
        current_user.username if current_user.is_authenticated else None,
        filename,
        source,
    )

    token_uri = request.url_root.rstrip('/') + f"/static/uploads/{filename}"
    try:
        tx = mint_on_chain(chain, wallet, token_uri)
        message = 'NFT minted on-chain'
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE marketplace_items SET minted=1 WHERE id=?', (item_id,))
            conn.commit()
    except Exception as e:
        tx = None
        message = f'Blockchain mint failed: {e}'

    return jsonify(status='success', success=True, message=message,
                   file=filename, tx_hash=tx)

@app.route('/api/mint-voice', methods=['POST'])
def mint_voice():
    """Backward compatible endpoint for voice-changer.js"""
    return mint_nft()

@app.route('/api/mint-voice-nft', methods=['POST'])
def mint_voice_nft():
    """Alias for older template"""
    return mint_nft()

# ── 7) Admin CRUD APIs ──────────────────────────────────────────────────────────
@app.route('/api/collections', methods=['GET', 'POST'])
@login_required
def collections_api():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            c.execute("INSERT INTO collections (name) VALUES (?)", (name,))
            conn.commit()
            return jsonify({"status": "Collection added"}), 201
        c.execute("SELECT * FROM collections")
        results = [{"id": row[0], "name": row[1]} for row in c.fetchall()]
        return jsonify(results)

@app.route('/api/archetypes', methods=['GET', 'POST'])
@login_required
def archetypes_api():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            collection_id = request.json.get('collection_id')
            c.execute("INSERT INTO archetypes (name, collection_id) VALUES (?, ?)", (name, collection_id))
            conn.commit()
            return jsonify({"status": "Archetype added"}), 201
        c.execute("SELECT * FROM archetypes")
        results = [{"id": row[0], "name": row[1], "collection_id": row[2]} for row in c.fetchall()]
        return jsonify(results)

@app.route('/api/tokens', methods=['GET', 'POST'])
@login_required
def tokens_api():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            archetype_id = request.json.get('archetype_id')
            c.execute("INSERT INTO tokens (name, archetype_id) VALUES (?, ?)", (name, archetype_id))
            conn.commit()
            return jsonify({"status": "Token added"}), 201
        c.execute("SELECT * FROM tokens")
        results = [{"id": row[0], "name": row[1], "archetype_id": row[2]} for row in c.fetchall()]
        return jsonify(results)

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def settings_api():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'POST':
            updates = request.json or {}
            for key, value in updates.items():
                c.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
            conn.commit()
            return jsonify(status='Settings updated')
        c.execute('SELECT key, value FROM settings')
        rows = c.fetchall()
        return jsonify({k: v for k, v in rows})

@app.route('/api/tip-wallets', methods=['GET', 'POST'])
def tip_wallets_api():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify(status='Error', message='Unauthorized'), 401
        token = (request.json.get('token') or '').upper()
        address = request.json.get('address')
        if not token or not address:
            return jsonify(status='Error', message='Missing token or address'), 400
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('REPLACE INTO tip_wallets (token, address) VALUES (?, ?)', (token, address))
            conn.commit()
        return jsonify(status='Updated')
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT token, address FROM tip_wallets')
        rows = c.fetchall()
    return jsonify({t: a for t, a in rows})


@app.route('/api/record-payment', methods=['POST'])
def record_payment():
    """Record a token transfer to the pool."""
    data = request.json or {}
    wallet = data.get('wallet')
    chain = data.get('chain')
    token = data.get('token')
    amount = data.get('amount')
    tx_id = data.get('tx_id')
    if not all([wallet, chain, token, amount, tx_id]):
        return jsonify(status='error', message='Missing fields'), 400
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO pool_payments (wallet, chain, token, amount, tx_hash) VALUES (?, ?, ?, ?, ?)",
            (wallet, chain, token, amount, tx_id)
        )
        conn.commit()
    return jsonify(status='success')


# ── 8) Frontend Routes ──────────────────────────────────────────────────────────
@app.route('/')
@wallet_login_required
def home():
    dapps = [
        {"title": "Voice Changer", "desc": "Real-time voice effects", "route": "/voice-changer"},
        {"title": "Quest Board", "desc": "Earn tokens via blockchain quests", "route": "/quest-board"},
        {"title": "NFT Viewer", "desc": "Connect wallet to view NFTs", "route": "/nft-viewer"},
        {"title": "Marketplace", "desc": "Buy & sell assets", "route": "/marketplace"},
        {"title": "Token Mixer", "desc": "Blend tokens into new assets", "route": "/token-mixer"}
    ]
    return render_template('index.html', dapps=dapps)

@app.route('/voice-changer')
@wallet_login_required
def voice_changer():
    solana_rpc = os.getenv('SOLANA_RPC', 'https://solana-mainnet.rpcpool.com')
    return render_template('voice-changer.html', solana_rpc=solana_rpc)

@app.route('/quest-board')
@wallet_login_required
def quest_board():
    return render_template('quest-board.html')

@app.route('/nft-viewer')
@wallet_login_required
def nft_viewer():
    return render_template('nft-viewer.html')

@app.route('/marketplace')
@wallet_login_required
def marketplace():
    return render_template('marketplace.html')

@app.route('/token-mixer')
@wallet_login_required
def token_mixer():
    return render_template('token-mixer.html')

@app.route('/game')
@wallet_login_required
def game_portal():
    return render_template('game.html')

@app.route('/tracker')
@wallet_login_required
def token_tracker_page():
    """Display NFT and reward statistics across chains."""
    return render_template('tracker.html')

@app.route('/active-users')
@wallet_login_required
def active_users_page():
    """Show currently active users with live updates."""
    return render_template('active-users.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        hashed = generate_password_hash(pwd)
        wallet = request.form.get('wallet')
        if wallet:
            wallet = wallet.lower()
        if not wallet:
            return render_template('signup.html', error='Wallet required')
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users WHERE wallet=?', (wallet,))
            if c.fetchone()[0] >= 2:
                return render_template('signup.html', error='Maximum usernames reached for this wallet')
            try:
                c.execute(
                    'INSERT INTO users (username, password, wallet) VALUES (?, ?, ?)',
                    (uname, hashed, wallet)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return render_template('signup.html', error='Username already exists')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        wallet = request.form.get('wallet')
        if wallet:
            wallet = wallet.lower()
        if not wallet:
            return render_template('login.html', error='Wallet connection required')

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id, username, password FROM users WHERE wallet=? AND username=?',
                (wallet, username)
            )
            row = c.fetchone()

        if not row or not check_password_hash(row[2], password):
            return render_template('login.html', error='Invalid credentials')

        user = User(id=row[0], username=row[1])
        session.permanent = True
        login_user(user, remember=True)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO login_events (user_id, wallet) VALUES (?, ?)',
                (user.id, wallet)
            )
            conn.commit()
        session['wallet'] = wallet
        if wallet == ADMIN_WALLET and username == ADMIN_USERNAME:
            return redirect(url_for('admin_panel'))
        return redirect(url_for('home'))

    return render_template('login.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        username = request.form['username']
        wallet = request.form.get('wallet')
        new_password = request.form['new_password']
        confirm = request.form['confirm_password']
        if wallet:
            wallet = wallet.lower()
        if not wallet:
            return render_template('reset-password.html', error='Wallet connection required')
        if new_password != confirm:
            return render_template('reset-password.html', error='Passwords do not match')
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                'SELECT id FROM users WHERE wallet=? AND username=?',
                (wallet, username)
            )
            row = c.fetchone()
            if not row:
                return render_template('reset-password.html', error='User not found')
            hashed = generate_password_hash(new_password)
            c.execute('UPDATE users SET password=? WHERE id=?', (hashed, row[0]))
            conn.commit()
        return redirect(url_for('login'))
    return render_template('reset-password.html')

@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    """Log out the current user.

    Supports both GET and POST requests so that JavaScript can invoke it using
    ``navigator.sendBeacon`` when the page unloads.
    """
    logout_user()
    session.permanent = False
    session.pop('wallet', None)

    # sendBeacon issues a POST request without waiting for a response. Returning
    # a short 204 response avoids unnecessary redirects during that flow.
    if request.method == 'POST':
        return ('', 204)

    return redirect(url_for('home'))

@app.route('/admin')
@login_required
def admin_panel():
    wallet = (session.get('wallet') or '').lower()
    if current_user.username != ADMIN_USERNAME or wallet != ADMIN_WALLET:
        return redirect(url_for('home'))
    return render_template('admin.html', user=current_user.username)

# Endpoint to finalize the current user's live recording manually
@app.route('/finalize', methods=['POST'])
@login_required
def trigger_finalize():
    """Trigger background finalization of the active live recording."""
    wallet = session.get('wallet')
    if not wallet:
        return "No wallet in session", 400
    eventlet.spawn(finalize_live_recording, current_user.username, wallet)
    return "", 204

# ── 9) Chat Events ────────────────────────────────────────────────────────────

@socketio.on('connect')
def chat_connect():
    """Allow all clients to fetch recent chat history on connect."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user, message, timestamp FROM chat_messages ORDER BY id DESC LIMIT 50"
        )
        rows = c.fetchall()
        history = [
            {"user": r[0], "message": r[1], "timestamp": r[2]} for r in rows[::-1]
        ]
    socketio.emit("chat_history", history, to=request.sid)
    # Send list of currently streaming users to the newly connected client
    socketio.emit('live_users', list(LIVE_STREAMERS.keys()), to=request.sid)


@socketio.on('get_chat_history')
def get_chat_history():
    """Send recent chat messages to the requesting client."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user, message, timestamp FROM chat_messages ORDER BY id DESC LIMIT 50"
        )
        rows = c.fetchall()
        history = [
            {"user": r[0], "message": r[1], "timestamp": r[2]} for r in rows[::-1]
        ]
    emit("chat_history", history)


@socketio.on('chat_message')
def handle_chat_message(data):
    """Broadcast chat messages from authenticated users only."""
    msg = (data.get('message') or '').strip()
    if not msg:
        return
    if not current_user.is_authenticated:
        emit('chat_error', 'Login required to send messages.')
        return
    username = current_user.username
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO chat_messages (user, message) VALUES (?, ?)",
            (username, msg),
        )
        conn.commit()
    socketio.emit('chat_message', {
        'user': username,
        'message': msg
    })

# --- Active User Tracking Events ---

@socketio.on('user_ping')
def handle_user_ping():
    """Update activity timestamp for the current user."""
    if current_user.is_authenticated:
        active_users[current_user.username] = datetime.utcnow().timestamp()
        sid_to_user[request.sid] = current_user.username
        sid_to_wallet[request.sid] = session.get('wallet')
        socketio.emit('active_user_update', {
            'users': get_active_users(),
            'count': len(get_active_users())
        })


@socketio.event
def disconnect():
    sid = request.sid
    print(f"Client {sid} disconnected")
    user = sid_to_user.pop(sid, None)
    wallet = sid_to_wallet.pop(sid, None)
    if user and user in active_users:
        active_users.pop(user, None)
        socketio.emit('active_user_update', {
            'users': get_active_users(),
            'count': len(get_active_users())
        })
    # remove from listener and speaker lists
    for host, listeners in LIVE_LISTENERS.items():
        if sid in listeners:
            listeners.discard(sid)
            broadcast_listeners(host)
    for host, speakers in LIVE_SPEAKERS.items():
        speakers.discard(sid)

    # if the disconnecting client was a live streamer, clean up
    for host, host_sid in list(LIVE_STREAMERS.items()):
        if host_sid == sid:
            wallet = LIVE_STREAMER_WALLETS.get(host)

            eventlet.spawn_after(1.0, finalize_live_recording, host, wallet)
            LIVE_STREAMERS.pop(host, None)
            LIVE_STREAMER_WALLETS.pop(host, None)
            LIVE_LISTENERS.pop(host, None)
            LIVE_SPEAKERS.pop(host, None)
            socketio.emit('live_users', list(LIVE_STREAMERS.keys()))
            broadcast_listeners(host)



# ── Live Voice Streaming Events ─────────────────────────────────────────────
@socketio.on('start_live')
def start_live():
    if not current_user.is_authenticated:
        return
    LIVE_STREAMERS[current_user.username] = request.sid
    LIVE_STREAMER_WALLETS[current_user.username] = session.get('wallet')
    LIVE_LISTENERS.setdefault(current_user.username, set())
    LIVE_SPEAKERS.setdefault(current_user.username, set())
    LIVE_RECORDINGS[current_user.username] = []
    socketio.emit('live_users', list(LIVE_STREAMERS.keys()))
    broadcast_listeners(current_user.username)


@socketio.on('stop_live')
def stop_live():
    if not current_user.is_authenticated:
        return
    host = current_user.username
    sid = request.sid
    wallet = session.get('wallet') or LIVE_STREAMER_WALLETS.get(host)

    eventlet.spawn_after(1.0, finalize_live_recording, host, wallet, sid)

    LIVE_STREAMERS.pop(host, None)
    LIVE_STREAMER_WALLETS.pop(host, None)
    LIVE_LISTENERS.pop(host, None)
    LIVE_SPEAKERS.pop(host, None)
    socketio.emit('live_users', list(LIVE_STREAMERS.keys()))
    broadcast_listeners(host)


@socketio.on('tune_in')
def tune_in(data):
    host = data.get('host') or data.get('user')
    if not host or host not in LIVE_STREAMERS:
        return
    LIVE_LISTENERS.setdefault(host, set()).add(request.sid)
    join_room(f'listen_{host}')
    emit('tuned_in', {'host': host})
    broadcast_listeners(host)


@socketio.on('add_speaker')
def add_speaker(data):
    host = data.get('host')
    user = data.get('user')
    if not host or host not in LIVE_STREAMERS or not user:
        return
    if LIVE_STREAMERS[host] != request.sid:
        return
    speakers = LIVE_SPEAKERS.setdefault(host, set())
    for sid, uname in list(sid_to_user.items()):
        if uname == user:
            speakers.add(sid)


@socketio.on('remove_speaker')
def remove_speaker(data):
    host = data.get('host')
    user = data.get('user')
    if not host or host not in LIVE_STREAMERS or not user:
        return
    if LIVE_STREAMERS[host] != request.sid:
        return
    speakers = LIVE_SPEAKERS.get(host, set())
    for sid in list(speakers):
        if sid_to_user.get(sid) == user:
            speakers.remove(sid)


@socketio.on('voice_chunk')
def voice_chunk(data):
    host = data.get('host') or data.get('user')
    chunk_b64 = data.get('chunk')
    mime = data.get('mime')

    if not host or host not in LIVE_STREAMERS:
        return

    sid = request.sid
    sender_is_host = LIVE_STREAMERS[host] == sid
    sender_is_speaker = sid in LIVE_SPEAKERS.get(host, set())

    if not sender_is_host and not sender_is_speaker:
        return

    try:
        chunk_bytes = base64.b64decode(chunk_b64)
    except Exception:
        return

    rec = LIVE_RECORDINGS.get(host)
    if rec is not None:
        rec.append(chunk_bytes)

    socketio.emit(
        'voice_chunk',
        {
            'host': host,
            'speaker': sid_to_user.get(sid, ''),
            'chunk': chunk_b64,
            'mime': mime,
        },
        room=f'listen_{host}'
    )


# ── 9) Static & Runner ──────────────────────────────────────────────────────────
@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

# Expose app and socketio for Gunicorn with eventlet
# Gunicorn command: gunicorn -k eventlet -w 1 --bind 0.0.0.0:$PORT main:app

if __name__ == "__main__":
    # Only used for local development
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
