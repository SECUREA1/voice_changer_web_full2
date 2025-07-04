"""
Blueprint: /voice_changer/*
Handles:  start/stop live stream  •  short recording (0.001-3 s)
          Emits “voice_frame” chunks over Socket.IO to the browser.
"""
import os, queue, time, io, wave, threading, uuid
from flask import Blueprint, jsonify, request, session
from flask_login import current_user
from db import add_user_audio
import numpy as np

# -------- optional local mic support -----------------------------------
AUDIO_LOCAL = os.getenv("AUDIO_MODEL_LOCAL", "0") == "1"
if AUDIO_LOCAL:
    try:
        import sounddevice as sd
        import librosa
    except ImportError:
        AUDIO_LOCAL = False

voice_bp   = Blueprint("voice_changer", __name__, url_prefix="/voice_changer")
_socketio  = None                      # set from app.py via register_socketio

# -------- effect parameters & helpers ---------------------------------
FX_PARAMS = {
    "effect": "none",      # none, robot, chipmunk, deep, squirrel
    "pitch_shift": 0.0,
    "speed": 1.0,
    "volume": 1.0,
    "echo": 0.0,
}
FX_LOCK = threading.Lock()
ECHO_BUF = np.zeros(44100*2, np.float32)
ECHO_IDX = 0


# ======================  internal stream class  =========================
if AUDIO_LOCAL:
    class VoiceStreamer:
        def __init__(self, sr=44100, block=1024):
            self.sr, self.block = sr, block
            self._q       = queue.Queue()
            self._running = threading.Event()
            self._rec     = False
            self._buf     = []
            self._stream  = None

        # ----------------- DSP helpers -----------------
        @staticmethod
        def _fx(data, sr):
            y = data.astype(np.float32) / 32768.0
            with FX_LOCK:
                p = FX_PARAMS.copy()

            # base pitch & speed from sliders
            if abs(p.get("pitch_shift", 0.0)) > 0.001:
                y = librosa.effects.pitch_shift(
                    y, sr, p["pitch_shift"], n_fft=min(len(y), 1024)
                )
            if abs(p.get("speed", 1.0) - 1.0) > 0.001:
                try:
                    y = librosa.effects.time_stretch(y, rate=p["speed"])
                except Exception:
                    pass

            eff = p.get("effect", "none")
            if eff == "chipmunk":
                y = librosa.effects.pitch_shift(y, sr, 6, n_fft=min(len(y), 1024))
            elif eff == "deep":
                y = librosa.effects.pitch_shift(y, sr, -6, n_fft=min(len(y), 1024))
            elif eff == "squirrel":
                y = librosa.effects.pitch_shift(y, sr, 10, n_fft=min(len(y), 1024))
                y = librosa.effects.time_stretch(y, 1.3)
            elif eff == "robot":
                y = librosa.effects.pitch_shift(y, sr, -5, n_fft=min(len(y), 1024))

            # echo using circular buffer
            if p.get("echo", 0.0) > 0:
                global ECHO_IDX
                delay = min(int(p["echo"] * sr), len(ECHO_BUF) - 1)
                out = np.empty_like(y)
                for i in range(len(y)):
                    idx = (ECHO_IDX - delay + len(ECHO_BUF)) % len(ECHO_BUF)
                    out[i] = y[i] + 0.5 * ECHO_BUF[idx]
                    ECHO_BUF[ECHO_IDX] = y[i]
                    ECHO_IDX = (ECHO_IDX + 1) % len(ECHO_BUF)
                y = out
            else:
                for i in range(len(y)):
                    ECHO_BUF[ECHO_IDX] = y[i]
                    ECHO_IDX = (ECHO_IDX + 1) % len(ECHO_BUF)

            y *= p.get("volume", 1.0)
            y = np.clip(y, -1.0, 1.0)
            return (y * 32768).astype(np.int16)

        def _callback(self, indata, frames, time_, status):
            if status:
                print("SD-status:", status)
            raw = indata[:, 0].copy()
            self._q.put(raw.tobytes())

        def _worker(self):
            while self._running.is_set():
                try:
                    chunk = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                processed = self._fx(np.frombuffer(chunk, np.int16), self.sr)
                if self._rec:
                    self._buf.append(processed.tobytes())
                if _socketio:
                    _socketio.emit(
                        "voice_frame",
                        processed.tobytes(),
                        namespace="/voice",
                    )

        # ----------------- public ctrl -----------------
        def start(self):
            if self._running.is_set(): return
            self._running.set()
            self._stream = sd.InputStream(channels=1, samplerate=self.sr,
                                          blocksize=self.block, dtype="int16",
                                          callback=self._callback)
            self._stream.start()
            threading.Thread(target=self._worker, daemon=True).start()

        def stop(self):
            if not self._running.is_set(): return
            self._running.clear()
            try:
                self._stream.stop()
                self._stream.close()
            except OSError as e:
                if e.errno != 9:
                    raise
            self._stream = None
            self._q = queue.Queue()

        # recording
        def rec_start(self):
            self._buf.clear(); self._rec = True; self._t0 = time.time()

        def rec_stop(self):
            self._rec = False
            dur = time.time() - self._t0
            if not 0.001 <= dur <= 3:
                return None, "Duration must be 0.001-3 s"
            pcm = b"".join(self._buf)
            return self._to_wav(pcm), None

        def _to_wav(self, pcm):
            bio = io.BytesIO()
            with wave.open(bio, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(self.sr)
                wf.writeframes(pcm)
            return bio.getvalue()

    _streamer = VoiceStreamer()
else:
    _streamer = None   # mic not available – endpoints will 501


# ======================  REST endpoints  ================================
def _err(): return jsonify(error="Audio not enabled on this server"), 501

@voice_bp.route("/start_stream", methods=["POST"])
def start_stream():
    if not _streamer: return _err()
    _streamer.start(); return jsonify(status="streaming")

@voice_bp.route("/stop_stream", methods=["POST"])
def stop_stream():
    if not _streamer: return _err()
    _streamer.stop();  return jsonify(status="stopped")

@voice_bp.route("/start_record", methods=["POST"])
def start_record():
    if not _streamer: return _err()
    _streamer.rec_start(); return jsonify(status="recording")

@voice_bp.route("/stop_record", methods=["POST"])
def stop_record():
    if not _streamer: return _err()
    wav, err = _streamer.rec_stop()
    if err: return jsonify(error=err), 400
    import base64
    b64 = base64.b64encode(wav).decode()

    filename = f"{uuid.uuid4().hex}_voice.wav"
    path = os.path.join('static', 'uploads', filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(wav)

    wallet = session.get('wallet')
    username = current_user.username if current_user.is_authenticated else None
    if wallet:
        add_user_audio(wallet, username, filename, 'voice_changer')

    return jsonify(wav=b64, file_url=f"/static/uploads/{filename}")

@voice_bp.route('/api/params', methods=['POST'])
def update_params():
    if not _streamer:
        return _err()
    data = request.get_json(silent=True) or {}
    with FX_LOCK:
        for k in ['effect', 'pitch_shift', 'speed', 'volume', 'echo']:
            if k in data:
                FX_PARAMS[k] = data[k]
    return jsonify(status='ok', params=FX_PARAMS)

# ======================  helper for app.py  =============================
def register_socketio(sio):
    global _socketio
    _socketio = sio
