from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room
from functools import wraps
from web3 import Web3
import requests
import sqlite3
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from datetime import timedelta
import time
from db import DB_PATH, init_db, add_user_audio, get_user_audio
import logging

# Flask-Login setup
logging.basicConfig(level=logging.INFO)
login_manager = LoginManager()

# SocketIO setup (ensure use of eventlet in production)
socketio = SocketIO(cors_allowed_origins="*", async_mode="eventlet")

# Upload configuration
UPLOAD_FOLDER = os.path.join(os.getcwd(), "static", "uploads")
ALLOWED_EXTENSIONS = {"mp3", "wav"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# admin settings
ADMIN_WALLET = "0xbe3b933b149f78dceefe99c4859c10a561c9e4cf"
ADMIN_USERNAME = "chaines"

# state for live streams and active users
LIVE_STREAMERS = {}
LIVE_LISTENERS = {}
LIVE_SPEAKERS = {}
active_users = {}
sid_to_user = {}

def get_active_users(timeout: int = 60):
    now = time.time()
    return [u for u, t in active_users.items() if now - t <= timeout]



# ERC20 ABI for Web3 token checking
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]

# User class
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return User(id=result[0], username=result[1])
    return None

# Require both login and wallet connection for HTML views
def wallet_login_required(func):
    """Allow pages to load without forcing login."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Login used to be mandatory for every page which blocked dapp access.
        # Now the route is always accessible so wallets can connect directly.
        return func(*args, **kwargs)

    return wrapper


# Main app factory
def create_app():
    app = Flask(__name__, static_url_path='/static')
    app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")
    CORS(app)
    CSRFProtect(app)
    app.permanent_session_lifetime = timedelta(days=7)

    # init auth + websockets
    login_manager.init_app(app)
    login_manager.login_view = "login"
    socketio.init_app(app)
    app.logger.setLevel(logging.INFO)

    # register blueprints
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
    voice_bp.register_socketio(socketio)

    # init database
    init_db()

    @app.context_processor
    def inject_session_data():
        return {
            'session_wallet': session.get('wallet'),
            'session_username': current_user.username if current_user.is_authenticated else ''
        }

    # Web3 setup
    ETH_RPC        = os.getenv("ETH_RPC", "https://mainnet.infura.io/v3/e252a3114f6f48a6aa8376e2e5b9dbfb")
    BSC_RPC        = os.getenv("BSC_RPC", "https://bsc-rpc.publicnode.com")
    CARDANO_API    = os.getenv("CARDANO_API", "https://cardano-mainnet.blockfrost.io/api/v0")
    BLOCKFROST_KEY = os.getenv("BLOCKFROST_KEY", "your_blockfrost_api_key")

    ETH_token_addr = os.getenv(
        "ETH_USDT_ADDRESS",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    )
    BSC_token_addr = os.getenv(
        "BSC_USDT_ADDRESS",
        "0x55d398326f99059fF775485246999027B3197955",
    )
    ADA_token_asset = os.getenv("ADA_USDT_ASSET", "")

    eth_web3 = Web3(Web3.HTTPProvider(ETH_RPC))
    bsc_web3 = Web3(Web3.HTTPProvider(BSC_RPC))
    erc20_contract_eth = eth_web3.eth.contract(
        address=Web3.to_checksum_address(ETH_token_addr),
        abi=ERC20_ABI
    )
    erc20_contract_bsc = bsc_web3.eth.contract(
        address=Web3.to_checksum_address(BSC_token_addr),
        abi=ERC20_ABI
    )

    # === ROUTES ===

    @app.route('/')
    @wallet_login_required
    def home():
        dapps = [
            {"title": "Voice Changer", "description": "Real-time voice effects", "route": "/voice-changer"},
            {"title": "Quest Board", "description": "Earn tokens via blockchain quests", "route": "/quest-board"},
            {"title": "NFT Viewer", "description": "Connect your wallet to view NFTs", "route": "/nft-viewer"},
            {"title": "Marketplace", "description": "Buy & sell NFTs or assets", "route": "/marketplace"},
            {"title": "Token Mixer", "description": "Blend tokens to create assets", "route": "/token-mixer"},
            {"title": "RedNode", "description": "AI-powered node system", "route": "/rednode"},
        ]
        return render_template('index.html', dapps=dapps)

    @app.route('/voice-changer')
    @wallet_login_required
    def voice_changer():
        return render_template('voice-changer.html')

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

    @app.route('/rednode')
    @wallet_login_required
    def rednode_page():
        return render_template('rednode.html')

    @app.route('/game')
    @wallet_login_required
    def game_portal():
        return render_template('game.html')

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            hashed = generate_password_hash(password)
            wallet = request.form.get('wallet')
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                try:
                    c.execute('INSERT INTO users (username, password, wallet) VALUES (?, ?, ?)', (username, hashed, wallet))
                    conn.commit()
                except sqlite3.IntegrityError:
                    return render_template('signup.html', error='Username exists')
            return redirect(url_for('login'))
        return render_template('signup.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            wallet = request.form.get('wallet')
            app.logger.info(f"Login attempt for {username}")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT id, username, password FROM users WHERE username=?",
                (username,)
            )
            result = c.fetchone()
            conn.close()
            if result and check_password_hash(result[2], password):
                user = User(id=result[0], username=result[1])
                login_user(user)
                if wallet:
                    session['wallet'] = wallet
                app.logger.info(f"Login success for {username}")
                return redirect(url_for('home'))
            else:
                app.logger.warning(f"Invalid login for {username}")
                return render_template('login.html', error="Invalid credentials")
        return render_template('login.html')

    @app.route('/logout', methods=['GET', 'POST'])
    def logout():
        logout_user()
        session.pop('wallet', None)
        return redirect(url_for('home'))

    @app.route('/admin')
    @login_required
    def admin_panel():
        wallet = (session.get('wallet') or '').lower()
        if current_user.username != ADMIN_USERNAME or wallet != ADMIN_WALLET:
            return redirect(url_for('home'))
        return render_template('admin.html', user=current_user.username)

    @app.route('/api/collections', methods=['GET', 'POST'])
    @login_required
    def collections_api():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            c.execute("INSERT INTO collections (name) VALUES (?)", (name,))
            conn.commit()
            conn.close()
            return jsonify({"status": "Collection added"}), 201
        c.execute("SELECT * FROM collections")
        results = [{"id": r[0], "name": r[1]} for r in c.fetchall()]
        conn.close()
        return jsonify(results)

    @app.route('/api/archetypes', methods=['GET', 'POST'])
    @login_required
    def archetypes_api():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            collection_id = request.json.get('collection_id')
            c.execute(
                "INSERT INTO archetypes (name, collection_id) VALUES (?, ?)",
                (name, collection_id)
            )
            conn.commit()
            conn.close()
            return jsonify({"status": "Archetype added"}), 201
        c.execute("SELECT * FROM archetypes")
        results = [
            {"id": r[0], "name": r[1], "collection_id": r[2]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify(results)

    @app.route('/api/tokens', methods=['GET', 'POST'])
    @login_required
    def tokens_api():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if request.method == 'POST':
            name = request.json.get('name')
            archetype_id = request.json.get('archetype_id')
            c.execute(
                "INSERT INTO tokens (name, archetype_id) VALUES (?, ?)",
                (name, archetype_id)
            )
            conn.commit()
            conn.close()
            return jsonify({"status": "Token added"}), 201
        c.execute("SELECT * FROM tokens")
        results = [
            {"id": r[0], "name": r[1], "archetype_id": r[2]}
            for r in c.fetchall()
        ]
        conn.close()
        return jsonify(results)

    @app.route('/api/settings', methods=['GET', 'POST'])
    @login_required
    def settings_api():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if request.method == 'POST':
            updates = request.json or {}
            for key, value in updates.items():
                c.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
            conn.commit()
            conn.close()
            return jsonify({"status": "Settings updated"})
        c.execute('SELECT key, value FROM settings')
        results = {k: v for k, v in c.fetchall()}
        conn.close()
        return jsonify(results)

    @app.route('/api/claim', methods=['POST'])
    def claim_quest():
        data = request.json
        wallet = data.get('wallet')
        chain = data.get('chain')
        reward = int(data.get('reward', 0))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT * FROM leaderboard WHERE wallet=? AND chain=?",
            (wallet, chain)
        )
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
        conn.close()
        return jsonify({"status": "Success", "message": "Reward recorded."})

    @app.route('/api/leaderboard', methods=['GET'])
    def get_leaderboard():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT wallet, chain, rewards FROM leaderboard "
            "ORDER BY rewards DESC LIMIT 10"
        )
        top_players = [
            {"wallet": w, "chain": ch, "rewards": r}
            for w, ch, r in c.fetchall()
        ]
        conn.close()
        return jsonify(top_players)

    @app.route('/api/verify-token', methods=['POST'])
    def verify_token():
        data = request.json
        wallet = data.get("walletAddress")
        chain = data.get("chain")
        required_tokens = float(data.get("requiredTokens", 1))
        app.logger.info(f"Verify token for {wallet} on {chain}")

        try:
            if chain == 'ethereum':
                balance = eth_web3.fromWei(
                    erc20_contract_eth.functions.balanceOf(wallet).call(),
                    'ether'
                )
            elif chain == 'bsc':
                balance = bsc_web3.fromWei(
                    erc20_contract_bsc.functions.balanceOf(wallet).call(),
                    'ether'
                )
            elif chain == 'cardano':
                headers = {"project_id": BLOCKFROST_KEY}
                response = requests.get(
                    f"{CARDANO_API}/addresses/{wallet}",
                    headers=headers
                )
                response.raise_for_status()
                assets = response.json().get("amount", [])
                if ADA_token_asset:
                    balance = next(
                        (
                            float(a["quantity"]) / 1e6
                            for a in assets
                            if a["unit"] == ADA_token_asset
                        ),
                        0,
                    )
                else:
                    balance = next(
                        (
                            float(a["quantity"]) / 1e6
                            for a in assets
                            if a["unit"] == "lovelace"
                        ),
                        0,
                    )
            else:
                return jsonify({"status": "Error", "message": "Unsupported chain"}), 400

            if balance < required_tokens:
                return jsonify({
                    "status": "Error",
                    "balance": float(balance),
                    "message": "Insufficient tokens"
                }), 403

            return jsonify({
                "status": "Success",
                "balance": float(balance),
                "message": "Access granted"
            })
        except Exception as e:
            app.logger.error(f"Token verify error: {e}")
            return jsonify({"status": "Error", "message": str(e)}), 500

    @app.route('/api/user-audio')
    @login_required
    def user_audio_api():
        wallet = session.get('wallet')
        if not wallet:
            return jsonify(status='error', message='No wallet connected'), 400
        uploads = get_user_audio(wallet=wallet)
        for u in uploads:
            u['url'] = f"/static/uploads/{u['filename']}" if not u['filename'].startswith('mixed/') else f"/static/{u['filename']}"
        return jsonify(uploads)

    @app.route('/api/mint-nft', methods=['POST'])
    def mint_nft():
        title = request.form.get('title', 'New NFT')
        wallet = request.form.get('walletAddress') or request.form.get('wallet')
        chain = (request.form.get('chain') or 'ethereum').lower()
        app.logger.info(f"Audio upload from {wallet}")

        file = (
            request.files.get('mix') or
            request.files.get('audio') or
            request.files.get('voice')
        )
        if not file:
            segments = []
            for key in ('voice', 'beat', 'fx'):
                f = request.files.get(key)
                if f and f.filename.rsplit('.',1)[-1].lower() in ALLOWED_EXTENSIONS:
                    segments.append(AudioSegment.from_file(f))
            if not segments:
                return jsonify(success=False, status='error', message='No audio uploaded'), 400
            mix = segments[0]
            for seg in segments[1:]:
                mix = mix.overlay(seg)
            filename = f"{uuid.uuid4().hex}_mix.mp3"
            path = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
            mix.export(path, format='mp3')
            app.logger.info(f"Mixed audio saved {filename}")
        else:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                return jsonify(status='error', message='Unsupported format'), 400
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            app.logger.info(f"File saved {filename}")

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

        add_user_audio(wallet, current_user.username if current_user.is_authenticated else None, filename, 'upload')
        app.logger.info(f"Mint route completed for {filename}")
        return jsonify(status='success', file=filename, item_id=item_id)

    # ------ SocketIO events ------

    @socketio.on('connect')
    def chat_connect():
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user, message, timestamp FROM chat_messages ORDER BY id DESC LIMIT 50")
            rows = c.fetchall()
            history = [{"user": r[0], "message": r[1], "timestamp": r[2]} for r in rows[::-1]]
        socketio.emit('chat_history', history, to=request.sid)

    @socketio.on('get_chat_history')
    def get_chat_history():
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user, message, timestamp FROM chat_messages ORDER BY id DESC LIMIT 50")
            rows = c.fetchall()
            history = [{"user": r[0], "message": r[1], "timestamp": r[2]} for r in rows[::-1]]
        emit('chat_history', history)

    @socketio.on('chat_message')
    def handle_chat_message(data):
        msg = (data.get('message') or '').strip()
        if not msg:
            return
        if not current_user.is_authenticated:
            emit('chat_error', 'Login required to send messages.')
            return
        username = current_user.username
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('INSERT INTO chat_messages (user, message) VALUES (?, ?)', (username, msg))
            conn.commit()
        socketio.emit('chat_message', {'user': username, 'message': msg})

    @socketio.on('user_ping')
    def handle_user_ping():
        if current_user.is_authenticated:
            active_users[current_user.username] = time.time()
            sid_to_user[request.sid] = current_user.username
            socketio.emit('active_user_update', {
                'users': get_active_users(),
                'count': len(get_active_users())
            })

    @socketio.event
    def disconnect():
        sid = request.sid
        print(f"Client {sid} disconnected")
        user = sid_to_user.pop(sid, None)
        if user and user in active_users:
            active_users.pop(user, None)
            socketio.emit('active_user_update', {
                'users': get_active_users(),
                'count': len(get_active_users())
            })
        for host, listeners in LIVE_LISTENERS.items():
            listeners.discard(sid)
        for host, speakers in LIVE_SPEAKERS.items():
            speakers.discard(sid)

        # if the disconnecting client was streaming, remove them
        for host, host_sid in list(LIVE_STREAMERS.items()):
            if host_sid == sid:
                LIVE_STREAMERS.pop(host, None)
                LIVE_LISTENERS.pop(host, None)
                LIVE_SPEAKERS.pop(host, None)
                socketio.emit('live_users', list(LIVE_STREAMERS.keys()))

    @socketio.on('start_live')
    def start_live():
        if not current_user.is_authenticated:
            return
        LIVE_STREAMERS[current_user.username] = request.sid
        LIVE_LISTENERS.setdefault(current_user.username, set())
        LIVE_SPEAKERS.setdefault(current_user.username, set())
        socketio.emit('live_users', list(LIVE_STREAMERS.keys()))

    @socketio.on('stop_live')
    def stop_live():
        if not current_user.is_authenticated:
            return
        LIVE_STREAMERS.pop(current_user.username, None)
        LIVE_LISTENERS.pop(current_user.username, None)
        LIVE_SPEAKERS.pop(current_user.username, None)
        socketio.emit('live_users', list(LIVE_STREAMERS.keys()))

    @socketio.on('tune_in')
    def tune_in(data):
        host = data.get('host') or data.get('user')
        if not host or host not in LIVE_STREAMERS:
            return
        LIVE_LISTENERS.setdefault(host, set()).add(request.sid)
        join_room(f'listen_{host}')
        emit('tuned_in', {'host': host})

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
        chunk = data.get('chunk')
        mime = data.get('mime')
        if not host or host not in LIVE_STREAMERS:
            return
        sid = request.sid
        sender_is_host = LIVE_STREAMERS[host] == sid
        sender_is_speaker = sid in LIVE_SPEAKERS.get(host, set())
        if not sender_is_host and not sender_is_speaker:
            return
        socketio.emit('voice_chunk', {
            'host': host,
            'speaker': sid_to_user.get(sid, ''),
            'chunk': chunk,
            'mime': mime
        }, room=f'listen_{host}')

    @app.route('/static/<path:path>')
    def send_static(path):
        return send_from_directory('static', path)

    return app

app = create_app()

# Only run socketio server if executed directly, not when used by Gunicorn
if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
