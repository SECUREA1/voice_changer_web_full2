from flask import Blueprint

marketplace_bp = Blueprint("marketplace", __name__, url_prefix="/marketplace", template_folder="../templates")

from . import routes  # Ensure routes register with the blueprint
__all__ = ["marketplace_bp", "register_socketio"]

# Optional: SocketIO handlers
def register_socketio(socketio):
    @socketio.on("marketplace_event")
    def handle_marketplace_event(data):
        print("📡 Marketplace event:", data)
