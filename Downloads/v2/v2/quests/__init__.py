from flask import Blueprint

# Define the Quest Board blueprint
quest_bp = Blueprint("quest", __name__, url_prefix="/quests", template_folder="../templates")

# Import routes to bind them to this blueprint
from . import routes  # Ensure quest routes are registered
__all__ = ["quest_bp", "register_socketio"]

# Optional: Attach real-time event handling if desired
def register_socketio(socketio):
    @socketio.on("quest_update")
    def handle_quest_update(data):
        print("📡 Quest Update Received:", data)
