from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from web3 import Web3
import requests
import sqlite3
import os
from marketplace.routes import marketplace_bp
app.register_blueprint(marketplace_bp)
from token_mixer import mixer_bp
app.register_blueprint(mixer_bp)
from nft import nft_bp
app.register_blueprint(nft_bp)

app = Flask(__name__, static_url_path='/static')
app.secret_key = 'super_secret_key'
CORS(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ---------- Database Setup ----------
DB_PATH = os.getenv('APP_DB_PATH') or os.path.join('database', 'admin.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS collections (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS archetypes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, collection_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, archetype_id INTEGER)''')
    if not c.execute("SELECT * FROM users WHERE username='chaines'").fetchone():
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('chaines', 'winner'))
    conn.commit()
    conn.close()

init_db()

# ---------- LOGIN SETUP ----------
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

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


# ---------- Web3 Configuration ----------
ETH_RPC = "https://mainnet.infura.io/v3/e252a3114f6f48a6aa8376e2e5b9dbfb"
BSC_RPC = "https://bsc-rpc.publicnode.com"
CARDANO_API = "https://cardano-mainnet.blockfrost.io/api/v0"
BLOCKFROST_KEY = "your_blockfrost_api_key"

ETH_token_address = "0xYourERC20TokenAddress"
BSC_token_address = "0xYourBNBTokenAddress"
ERC20_ABI = [...]  # Load your ERC-20 ABI here


# … after you’ve read ETH_TOKEN and BSC_TOKEN from the environment …
eth_web3 = Web3(Web3.HTTPProvider(ETH_RPC))
bsc_web3 = Web3(Web3.HTTPProvider(BSC_RPC))

# fix: use the new method name
erc20_contract_eth = eth_web3.eth.contract(
    address=Web3.to_checksum_address(os.getenv("ETH_TOKEN")),  # ← changed here
    abi=ERC20_ABI
)
erc20_contract_bsc = bsc_web3.eth.contract(
    address=Web3.to_checksum_address(os.getenv("BSC_TOKEN")),  # ← and here
    abi=ERC20_ABI
)

# ---------- Leaderboard Table ----------
def ensure_leaderboard_table():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS leaderboard (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet TEXT,
        chain TEXT,
        rewards INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()


ensure_leaderboard_table()


@app.route('/api/claim', methods=['POST'])
def claim_quest():
    data = request.json
    wallet = data.get('wallet')
    chain = data.get('chain')
    reward = int(data.get('reward', 0))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT * FROM leaderboard WHERE wallet=? AND chain=?", (wallet, chain))
    row = c.fetchone()
    if row:
        c.execute("UPDATE leaderboard SET rewards = rewards + ? WHERE wallet=? AND chain=?", (reward, wallet, chain))
    else:
        c.execute("INSERT INTO leaderboard (wallet, chain, rewards) VALUES (?, ?, ?)", (wallet, chain, reward))

    conn.commit()
    conn.close()

    return jsonify({"status": "Success", "message": "Reward recorded."})


@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT wallet, chain, rewards FROM leaderboard ORDER BY rewards DESC LIMIT 10")
    top_players = [{"wallet": w, "chain": ch, "rewards": r} for w, ch, r in c.fetchall()]
    conn.close()
    return jsonify(top_players)


# ---------- API: Token Verification ----------
@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    data = request.json
    wallet = data.get("walletAddress")
    chain = data.get("chain")  # 'ethereum', 'bsc', or 'cardano'
    required_tokens = float(data.get("requiredTokens", 1))

    try:
        if chain == 'ethereum':
            balance = eth_web3.fromWei(erc20_contract_eth.functions.balanceOf(wallet).call(), 'ether')
        elif chain == 'bsc':
            balance = bsc_web3.fromWei(erc20_contract_bsc.functions.balanceOf(wallet).call(), 'ether')
        elif chain == 'cardano':
            headers = {"project_id": BLOCKFROST_KEY}
            response = requests.get(f"{CARDANO_API}/addresses/{wallet}", headers=headers)
            response.raise_for_status()
            assets = response.json().get("amount", [])
            ada_balance = next((float(a['quantity']) / 1e6 for a in assets if a["unit"] == "lovelace"), 0)
            balance = ada_balance
        else:
            return jsonify({"status": "Error", "message": "Unsupported chain"}), 400

        if balance < required_tokens:
            return jsonify({"status": "Error", "balance": float(balance), "message": "Insufficient tokens"}), 403

        return jsonify({"status": "Success", "balance": float(balance), "message": "Access granted"})

    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500

# ---------- FRONTEND ROUTES ----------
@app.route('/')
def home():
    dapps = [
        {"title": "Voice Changer", "description": "Real-time voice effects", "route": "/voice-changer"},
        {"title": "Quest Board", "description": "Earn tokens via blockchain quests", "route": "/quest-board"},
        {"title": "NFT Viewer", "description": "Connect your wallet to view NFTs", "route": "/nft-viewer"},
        {"title": "Marketplace", "description": "Buy & sell NFTs or assets", "route": "/marketplace"},  # ← New app
        {"title": "Token Mixer", "description": "Blend tokens to create new assets", "route": "/token-mixer"}  # ← New app
    ]
    return render_template('index.html', dapps=dapps)

@app.route('/voice-changer')
def voice_changer():
    return render_template('voice-changer.html')

@app.route('/quest-board')
def quest_board():
    return render_template('quest-board.html')

@app.route('/nft-viewer')
def nft_viewer():
    return render_template('nft-viewer.html')

@app.route('/marketplace')
def marketplace():
    return render_template('marketplace.html')

@app.route('/token-mixer')
def token_mixer():
    return render_template('token-mixer.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE username=? AND password=?", (username, password))
        result = c.fetchone()
        conn.close()
        if result:
            user = User(id=result[0], username=result[1])
            login_user(user)
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/admin')
@login_required
def admin_panel():
    return render_template('admin.html', user=current_user.username)

# ---------- API ROUTES ----------
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
    else:
        c.execute("SELECT * FROM collections")
        results = [{"id": row[0], "name": row[1]} for row in c.fetchall()]
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
        c.execute("INSERT INTO archetypes (name, collection_id) VALUES (?, ?)", (name, collection_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "Archetype added"}), 201
    else:
        c.execute("SELECT * FROM archetypes")
        results = [{"id": row[0], "name": row[1], "collection_id": row[2]} for row in c.fetchall()]
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
        c.execute("INSERT INTO tokens (name, archetype_id) VALUES (?, ?)", (name, archetype_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "Token added"}), 201
    else:
        c.execute("SELECT * FROM tokens")
        results = [{"id": row[0], "name": row[1], "archetype_id": row[2]} for row in c.fetchall()]
        conn.close()
        return jsonify(results)
    c.execute('''
        CREATE TABLE IF NOT EXISTS marketplace_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            wallet TEXT,
            filename TEXT,
            chain TEXT,
            type TEXT,
            price TEXT
        )
    ''')

# ---------- STATIC FILE SERVE FALLBACK ----------
@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

# ---------- RUN APP ----------
if __name__ == '__main__':
    app.run(debug=True, port=5000)
