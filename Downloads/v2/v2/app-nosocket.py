import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Try import for local audio support
AUDIO_ENABLED = False
try:
    # Only attempt on local/dev; set AUDIO_MODEL_LOCAL=1 for local audio use.
    if os.getenv("AUDIO_MODEL_LOCAL", "0") == "1":
        import sounddevice as sd
        import numpy as np
        import threading
        AUDIO_ENABLED = True
except ImportError:
    pass

# ===== Blueprint Import =====
try:
    from voice_changer.routes import voice_bp
except ImportError:
    raise ImportError("Missing module: 'voice_changer.routes'. Make sure the folder and __init__.py exist.")

# ===== Flask Setup =====
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_key")
CORS(app)
app.register_blueprint(voice_bp)

# ===== Audio (Local Only) =====
if AUDIO_ENABLED:
    fs = 44100
    block_size = 1024
    channels = 1

    class Parameters:
        def __init__(self):
            self.is_recording = False
            self.recorded_data = []
            self.stream_event = threading.Event()

    params = Parameters()
    audio_thread = None
    data_lock = threading.Lock()

    def audio_callback(indata, outdata, frames, time_info, status):
        if status:
            print("Stream Status:", status)
        audio_data = indata[:, 0].copy()
        audio_data *= 1.0
        if params.is_recording:
            with data_lock:
                params.recorded_data.append(audio_data.copy())
        outdata[:] = np.clip(audio_data, -1.0, 1.0).reshape(-1, channels)

    def start_audio_stream():
        with sd.Stream(channels=channels, samplerate=fs, blocksize=block_size, callback=audio_callback):
            while not params.stream_event.is_set():
                sd.sleep(100)

    @app.route("/api/start", methods=["POST"])
    def start_stream():
        global audio_thread
        if audio_thread and audio_thread.is_alive():
            return jsonify({"status": "Already running"})
        params.stream_event.clear()
        audio_thread = threading.Thread(target=start_audio_stream, daemon=True)
        audio_thread.start()
        return jsonify({"status": "Started"})

    @app.route("/api/stop", methods=["POST"])
    def stop_stream():
        params.stream_event.set()
        return jsonify({"status": "Stopped"})

    @app.route("/api/record", methods=["POST"])
    def record_audio():
        action = request.json.get("action")
        if action == "start":
            with data_lock:
                params.recorded_data = []
            params.is_recording = True
            return jsonify({"status": "Recording started"})
        elif action == "stop":
            params.is_recording = False
            return jsonify({"status": "Recording stopped"})
        return jsonify({"status": "Invalid action"}), 400

    @app.route("/api/playback", methods=["GET"])
    def playback_audio():
        with data_lock:
            if not params.recorded_data:
                return jsonify({"status": "No audio recorded"})
            data = np.concatenate(params.recorded_data)

        def callback(outdata, frames, time_info, status):
            nonlocal data
            if len(data) >= frames:
                outdata[:] = data[:frames].reshape(-1, channels)
                data = data[frames:]
            else:
                outdata[:len(data)] = data.reshape(-1, channels)
                outdata[len(data):] = 0
                raise sd.CallbackStop()

        try:
            with sd.OutputStream(channels=channels, samplerate=fs, callback=callback):
                sd.sleep(int(len(data) / fs * 1000) + 100)
        except Exception as e:
            return jsonify({"status": "Playback failed", "error": str(e)}), 500

        return jsonify({"status": "Playback complete"})

else:
    # Return "not supported" on cloud/server for audio APIs
    @app.route("/api/start", methods=["POST"])
    def start_stream_disabled():
        return jsonify({"status": "error", "message": "Audio features not available on this server."}), 501

    @app.route("/api/stop", methods=["POST"])
    def stop_stream_disabled():
        return jsonify({"status": "error", "message": "Audio features not available on this server."}), 501

    @app.route("/api/record", methods=["POST"])
    def record_audio_disabled():
        return jsonify({"status": "error", "message": "Audio features not available on this server."}), 501

    @app.route("/api/playback", methods=["GET"])
    def playback_audio_disabled():
        return jsonify({"status": "error", "message": "Audio features not available on this server."}), 501

# ===== Web Routes =====
@app.route("/")
def home():
    dapps = [
        {"title": "Voice Changer", "description": "Real-time voice effects", "route": "/voice-changer"},
        {"title": "Quest Board", "description": "Earn tokens via blockchain quests", "route": "/quest-board"},
        {"title": "NFT Viewer", "description": "Connect your wallet to view NFTs", "route": "/nft-viewer"},
        {"title": "Marketplace", "description": "Buy & sell NFTs or assets", "route": "/marketplace"},
        {"title": "Token Mixer", "description": "Blend tokens to create new assets", "route": "/token-mixer"}
    ]
    return render_template("index.html", dapps=dapps)

@app.route("/voice-changer")
def voice_changer():
    return render_template("voice-changer.html")

@app.route("/quest-board")
def quest_board():
    return render_template("quest-board.html")

@app.route("/nft-viewer")
def nft_viewer():
    return render_template("nft-viewer.html")

@app.route("/marketplace")
def marketplace():
    return render_template("marketplace.html")

@app.route("/token-mixer")
def token_mixer():
    return render_template("token-mixer.html")

# ===== Main Entry Point =====
if __name__ == "__main__":
    if app.secret_key == "dev_key":
        print("WARNING: Using development secret key! Set SECRET_KEY environment variable for production.")
    app.run(debug=True)
