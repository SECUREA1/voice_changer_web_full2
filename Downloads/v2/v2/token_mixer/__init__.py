from flask import Blueprint

# Define the Token Mixer blueprint
mixer_bp = Blueprint("token_mixer", __name__, url_prefix="/mixer", template_folder="../templates")

# Import routes to bind them to this blueprint
from . import routes  # noqa: F401
__all__ = ["mixer_bp", "register_socketio"]

# Optional: If your mixer uses real-time streaming (e.g. for playback feedback)
def register_socketio(socketio):
    @socketio.on("mixer_event")
    def handle_mixer_event(data):
        print("🎛️ Token Mixer Event Received:", data)
