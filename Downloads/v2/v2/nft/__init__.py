from flask import Blueprint

# ──────────────────────────────────────────────────────────────────────────────
# NFT Viewer Blueprint Setup
# ──────────────────────────────────────────────────────────────────────────────

# Create the blueprint, pointing to your templates dir
nft_bp = Blueprint(
    "nft",
    __name__,
    url_prefix="/nft",
    template_folder="../templates"   # adjust if your templates live elsewhere
)

# Import the route functions so they're registered on the blueprint
from . import routes  # noqa: E402,F401

# Public API of this module
__all__ = ["nft_bp", "register_socketio"]


def register_socketio(socketio):
    """
    Hook up any real-time NFT events over Socket.IO.
    Call this from your app (after socketio = SocketIO(app)):

        from nft import register_socketio
        register_socketio(socketio)
    """
    @socketio.on("nft_event")
    def handle_nft_event(data):
        # You can broadcast to clients, log, etc.
        print("📡 NFT Event Received:", data)
