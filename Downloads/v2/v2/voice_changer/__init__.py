from flask import Flask, render_template
from flask_cors import CORS
from flask_login import LoginManager
import os

# Blueprints
from voice_changer.routes import voice_bp
from token_mixer.routes import mixer_bp
from nft.routes import nft_bp
from quests.routes import quest_bp

# Constants
DB_PATH = os.getenv('APP_DB_PATH')
if DB_PATH:
    DB_DIR = os.path.dirname(DB_PATH)
else:
    DB_DIR = os.path.join(os.getcwd(), 'database')
    DB_PATH = os.path.join(DB_DIR, 'admin.db')


def create_app():
    app = Flask(__name__, static_url_path='/static')
    app.secret_key = 'super_secret_key'  # 🔐 Replace in production with env var
    CORS(app)

    # === LOGIN MANAGER SETUP ===
    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    # Dynamic import to avoid circular issues
    from auth.models import User
    from auth.db import get_user_by_id, init_db

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(user_id)

    # === DB INIT ===
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
    init_db(DB_PATH)

    # === REGISTER ROUTES ===
    app.register_blueprint(voice_bp, url_prefix='/voice')
    app.register_blueprint(mixer_bp, url_prefix='/mixer')
    app.register_blueprint(nft_bp, url_prefix='/nft')
    app.register_blueprint(quest_bp, url_prefix='/quests')

    # === MAIN WEB ENTRY ===
    @app.route('/')
    def home():
        dapps = [
            {"title": "Voice Changer", "description": "Real-time voice effects", "route": "/voice"},
            {"title": "Token Mixer", "description": "Blend audio NFTs into a new token", "route": "/mixer"},
            {"title": "NFT Viewer", "description": "3D audio NFTs with GLB/Video", "route": "/nft"},
            {"title": "Quest Board", "description": "Complete tasks, earn tokens", "route": "/quests"}
        ]
        return render_template("index.html", dapps=dapps)

    return app
