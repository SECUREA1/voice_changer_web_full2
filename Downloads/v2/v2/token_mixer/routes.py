# mixer/routes.py

import os
import uuid
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    send_file,
    current_app,
    url_for,
    session
)
from flask_login import current_user
from db import add_user_audio, DB_PATH
from pydub import AudioSegment
from werkzeug.utils import secure_filename

mixer_bp = Blueprint(
    "token_mixer",
    __name__,
    url_prefix="/token-mixer",
    template_folder="../templates"  # adjust if your templates live elsewhere
)

# where to save mixes - resolved lazily once an application context exists
def get_mixed_folder():
    """Return the folder used to store mixed tracks."""
    folder = os.path.join(current_app.static_folder, "mixed")
    os.makedirs(folder, exist_ok=True)
    return folder

ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "flac"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@mixer_bp.route("/", methods=["GET"])
def mixer_page():
    return render_template("token-mixer.html")

@mixer_bp.route("/api/mix", methods=["POST"])
def mix_tracks():
    # expect form-data with up to three files
    files = {
        "beat": request.files.get("beat"),
        "voice": request.files.get("voice"),
        "fx":    request.files.get("fx"),
    }

    # make sure at least one valid file
    tracks = []
    for name, f in files.items():
        if f and allowed_file(f.filename):
            # secure the filename and load
            tracks.append(AudioSegment.from_file(f))

    if not tracks:
        return jsonify({"status": "error", "message": "No supported audio files uploaded"}), 400

    # overlay them all
    mixed = tracks[0]
    for track in tracks[1:]:
        mixed = mixed.overlay(track)

    # export the mix
    mixed_folder = get_mixed_folder()
    filename = f"{uuid.uuid4().hex}_{secure_filename('mix.mp3')}"
    out_path = os.path.join(mixed_folder, filename)
    mixed.export(out_path, format="mp3")

    wallet = request.form.get("wallet") or session.get("wallet")
    username = current_user.username if current_user.is_authenticated else None
    if wallet:
        add_user_audio(wallet, username, os.path.join('mixed', filename), "token_mixer")

    download_url = url_for("token_mixer.download_mix", filename=filename, _external=True)
    return jsonify({
        "status":   "success",
        "message":  "Mix created",
        "mix_url":  download_url
    })

@mixer_bp.route("/api/download/<filename>", methods=["GET"])
def download_mix(filename):
    file_path = os.path.join(get_mixed_folder(), filename)
    if not os.path.exists(file_path):
        return jsonify({"status":"error","message":"File not found"}), 404
    return send_file(file_path, as_attachment=True, download_name=filename)
