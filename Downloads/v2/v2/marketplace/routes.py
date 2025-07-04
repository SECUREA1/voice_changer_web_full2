import os
import uuid
import sqlite3
import io
from flask import Blueprint, render_template, request, jsonify, send_file, abort, session
from werkzeug.utils import secure_filename
from flask_login import current_user
from db import DB_PATH, add_user_audio  # ← centralized in db.py
from blockchain import mint_nft as mint_on_chain, process_payment, payment_breakdown
import json

marketplace_bp = Blueprint("marketplace", __name__, url_prefix="/marketplace")

# --- Upload configuration ---
UPLOAD_FOLDER = os.path.join(os.getcwd(), "static", "uploads")
ALLOWED_EXTENSIONS = {"mp3", "wav", "glb", "mp4", "jpg", "jpeg", "png"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Ensure the marketplace_items table exists ---
def ensure_table():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
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
        # add missing columns when upgrading from older schema
        c.execute('PRAGMA table_info(marketplace_items)')
        cols = [r[1] for r in c.fetchall()]
        if 'description' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN description TEXT')
        if 'token' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN token TEXT DEFAULT "USDT"')
        if 'minted' not in cols:
            c.execute('ALTER TABLE marketplace_items ADD COLUMN minted INTEGER DEFAULT 0')
        c.execute('''
            CREATE TABLE IF NOT EXISTS marketplace_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                data BLOB,
                mime TEXT,
                filename TEXT
            )
        ''')
        c.execute('''
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
        ''')
ensure_table()

# --- Marketplace page ---
@marketplace_bp.route("/", methods=["GET"])
def index():
    return render_template("marketplace.html")

# --- Get items ---
@marketplace_bp.route("/api/items", methods=["GET"])
def get_items():
    chain_filter = request.args.get("chain", type=str)
    sql = (
        "SELECT mi.id, mi.title, mi.description, mi.filename, mi.chain, mi.token, mi.type, mi.price, mi.minted, mf.id "
        "FROM marketplace_items mi LEFT JOIN marketplace_files mf ON mi.id = mf.item_id"
    )
    params = []
    if chain_filter:
        sql += " WHERE mi.chain = ?"
        params.append(chain_filter.lower())

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()

    items = []
    for r in rows:
        item = {
            "id": r[0],
            "title": r[1],
            "description": r[2],
            "media_url": f"/static/uploads/{r[3]}",
            "chain": r[4],
            "token": r[5],
            "type": r[6],
            "price": r[7],
            "minted": bool(r[8]),
        }
        if r[9] is not None:
            item["file_url"] = f"/marketplace/api/file/{r[9]}"
        items.append(item)

    return jsonify(items)

# --- Upload new NFT (audio/video/image/model) ---
@marketplace_bp.route("/api/upload", methods=["POST"])
def upload_item():
    title       = request.form.get("title")
    description = request.form.get("description", "NFT Item")
    wallet      = request.form.get("wallet")
    file        = request.files.get("file")
    chain       = request.form.get("chain", "ethereum").lower()
    price       = request.form.get("price", "0.99")
    token       = request.form.get("token", "USDT").upper()

    if not all([title, wallet, file]):
        return jsonify({"status":"error","message":"Missing required fields"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"status":"error","message":f"Unsupported format: {ext}"}), 400

    # infer type
    if ext in {"mp3", "wav"}:
        nft_type = "audio"
    elif ext == "mp4":
        nft_type = "video"
    elif ext in {"jpg", "jpeg", "png"}:
        nft_type = "image"
    elif ext == "glb":
        nft_type = "model"
    else:
        nft_type = "unknown"

    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    with open(save_path, "rb") as f:
        file_data = f.read()

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO marketplace_items
            (title, description, wallet, filename, chain, token, type, price, minted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ''', (title, description, wallet, filename, chain, token, nft_type, price))
        item_id = c.lastrowid
        c.execute(
            "INSERT INTO marketplace_files (item_id, data, mime, filename) VALUES (?, ?, ?, ?)",
            (item_id, file_data, file.mimetype, filename),
        )

    add_user_audio(
        wallet,
        current_user.username if current_user.is_authenticated else None,
        filename,
        "marketplace",
    )

    return jsonify({
        "status":    "success",
        "message":   f"Uploaded '{title}'",
        "media_url": f"/static/uploads/{filename}",
        "type":      nft_type,
        "token":     token
    })

# --- Serve stored file ---
@marketplace_bp.route("/api/file/<int:file_id>", methods=["GET"])
def get_file(file_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT data, mime, filename FROM marketplace_files WHERE id=?", (file_id,))
        row = c.fetchone()
    if row:
        data, mime, fname = row
        return send_file(io.BytesIO(data), mimetype=mime, download_name=fname)
    abort(404)

# --- Purchase item ---
@marketplace_bp.route("/api/purchase", methods=["POST"])
def purchase_item():
    data    = request.get_json() or {}
    item_id = data.get("track_id")
    wallet  = data.get("wallet")
    chain   = data.get("chain")
    token   = data.get("token")
    if not all([item_id, wallet]):
        return jsonify(status="error", message="Missing fields"), 400
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT wallet, price, chain, token FROM marketplace_items WHERE id=?", (item_id,))
        row = c.fetchone()
        if not row:
            return jsonify(status="error", message="Item not found"), 404
        seller_wallet, price, item_chain, item_token = row

    if chain is None:
        chain = item_chain
    if token is None:
        token = item_token
    if chain != item_chain or token.upper() != item_token.upper():
        return jsonify(status="error", message="Payment option not available"), 400
    try:
        result = process_payment(chain, wallet, seller_wallet, float(price), token.upper())
    except NotImplementedError as e:
        return jsonify(status="error", message=str(e)), 501
    if isinstance(result, dict):
        return jsonify(status="needs_signature", tx=result)
    tx_hash = result
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO marketplace_orders
                (item_id, buyer_wallet, seller_wallet, chain, token, amount, tx_hash, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, wallet, seller_wallet, chain, token, price, tx_hash, "completed")
        )
        conn.commit()
    breakdown = payment_breakdown(float(price))
    return jsonify(status="success", tx_hash=tx_hash, breakdown=breakdown)

# --- Demo NFTs ---
@marketplace_bp.route("/api/demo_nfts", methods=["GET"])
def demo_nfts():
    return jsonify([
        {
            "id":          "eth001",
            "title":       "Lo-Fi Chill Pack",
            "description": "Lo-fi audio loops perfect for beatmakers and streamers.",
            "price":       "0.05",
            "chain":       "ethereum",
            "media_url":   "https://ipfs.io/ipfs/QmLoFiSampleAudio.mp3",
            "type":        "audio"
        },
        {
            "id":          "sol001",
            "title":       "3D Sound Stage",
            "description": "3D GLB sound stage model with immersive effects.",
            "price":       "1.20",
            "chain":       "solana",
            "media_url":   "https://ipfs.io/ipfs/Qm3DSoundStage.glb",
            "type":        "model"
        },
        {
            "id":          "ada001",
            "title":       "Bass Drop Visualizer",
            "description": "Epic bass drop video NFT for audio branding.",
            "price":       "1.50",
            "chain":       "cardano",
            "media_url":   "https://ipfs.io/ipfs/QmBassDropVideo.mp4",
            "type":        "video"
        }
    ])

# --- Save layered NFT without minting ---
@marketplace_bp.route("/api/save_layered", methods=["POST"])
def save_layered():
    """Store layered NFT assets for later minting."""
    title = request.form.get("title")
    description = request.form.get("description", "Layered NFT")
    wallet = request.form.get("wallet")
    chain = request.form.get("chain", "ethereum").lower()
    price = request.form.get("price", "0")
    token = request.form.get("token", "USDT").upper()

    if not all([title, wallet]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    glb_file = request.files.get("glb")
    video_file = request.files.get("video")
    audio_file = request.files.get("audio")
    image_file = request.files.get("image")
    if not any([glb_file, video_file, audio_file, image_file]):
        return jsonify({"status": "error", "message": "No media provided"}), 400

    draft_id = request.form.get("item_id", type=int)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if draft_id:
            item_id = draft_id
            c.execute(
                "UPDATE marketplace_items SET title=?, description=?, chain=?, token=?, price=? WHERE id=?",
                (title, description, chain, token, price, draft_id),
            )
            c.execute("DELETE FROM marketplace_files WHERE item_id=?", (draft_id,))
        else:
            c.execute(
                """
                INSERT INTO marketplace_items (title, description, wallet, filename, chain, token, type, price, minted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (title, description, wallet, "", chain, token, "layered", price),
            )
            item_id = c.lastrowid

        def save_layer(file_obj):
            if not file_obj:
                return
            fname = f"{uuid.uuid4().hex}_{secure_filename(file_obj.filename)}"
            path = os.path.join(UPLOAD_FOLDER, fname)
            file_obj.save(path)
            with open(path, "rb") as f:
                data = f.read()
            c.execute(
                "INSERT INTO marketplace_files (item_id, data, mime, filename) VALUES (?, ?, ?, ?)",
                (item_id, data, file_obj.mimetype, fname),
            )

        save_layer(image_file)
        save_layer(video_file)
        save_layer(glb_file)
        save_layer(audio_file)
        conn.commit()

    add_user_audio(
        wallet,
        current_user.username if current_user.is_authenticated else None,
        f"draft_{item_id}",
        "marketplace",
    )

    return jsonify(status="success", item_id=item_id)

# --- Mint layered NFT ---
@marketplace_bp.route("/api/mint_layered", methods=["POST"])
def mint_layered():
    """Mint a LayeredControlNFT with optional image, video, audio and GLB."""
    title = request.form.get("title")
    description = request.form.get("description", "Layered NFT")
    wallet = request.form.get("wallet")
    chain = request.form.get("chain", "ethereum").lower()
    price = request.form.get("price", "0")
    token = request.form.get("token", "USDT").upper()

    if not all([title, wallet]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    glb_file = request.files.get("glb")
    video_file = request.files.get("video")
    audio_file = request.files.get("audio")
    image_file = request.files.get("image")
    if not any([glb_file, video_file, audio_file, image_file]):
        return jsonify({"status": "error", "message": "No media provided"}), 400

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO marketplace_items (title, description, wallet, filename, chain, token, type, price, minted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (title, description, wallet, "", chain, token, "layered", price),
        )
        item_id = c.lastrowid

        layers = []
        def save_layer(file_obj, l_type):
            if not file_obj:
                return
            filename = f"{uuid.uuid4().hex}_{secure_filename(file_obj.filename)}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            file_obj.save(path)
            with open(path, "rb") as f:
                data = f.read()
            c.execute(
                "INSERT INTO marketplace_files (item_id, data, mime, filename) VALUES (?, ?, ?, ?)",
                (item_id, data, file_obj.mimetype, filename),
            )
            url = f"/static/uploads/{filename}"
            layers.append({
                "type": l_type,
                "media_type": file_obj.mimetype,
                "label": file_obj.filename,
                "url": url,
            })

        save_layer(image_file, "background")
        save_layer(video_file, "background")
        save_layer(glb_file, "foreground")
        save_layer(audio_file, "audio")

        metadata = {
            "name": title,
            "description": description,
            "nft_standard": "LayeredControlNFT-v1",
            "nft_type": "layered_control",
            "layers": layers,
        }
        meta_filename = f"{uuid.uuid4().hex}_metadata.json"
        meta_path = os.path.join(UPLOAD_FOLDER, meta_filename)
        with open(meta_path, "w") as f:
            json.dump(metadata, f)
        with open(meta_path, "rb") as f:
            meta_data = f.read()
        c.execute(
            "INSERT INTO marketplace_files (item_id, data, mime, filename) VALUES (?, ?, ?, ?)",
            (item_id, meta_data, "application/json", meta_filename),
        )
        c.execute("UPDATE marketplace_items SET filename=? WHERE id=?", (meta_filename, item_id))
        conn.commit()

    add_user_audio(
        wallet,
        current_user.username if current_user.is_authenticated else None,
        meta_filename,
        "marketplace",
    )

    token_uri = request.url_root.rstrip('/') + f"/static/uploads/{meta_filename}"
    try:
        tx = mint_on_chain(chain, wallet, token_uri, metadata)
        if tx:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('UPDATE marketplace_items SET minted=1 WHERE id=?', (item_id,))
                conn.commit()
    except Exception as e:
        tx = None
        print(f"Mint error: {e}")

    return jsonify({
        "status": "success",
        "metadata_url": f"/static/uploads/{meta_filename}",
        "token_uri": token_uri,
        "tx_hash": tx,
        "token": token,
    })
