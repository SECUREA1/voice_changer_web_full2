# voice_changer/routes.py
from flask import Blueprint, jsonify, request
from .processor import start_audio_stream, params, data_lock, update_effects
import threading
"""
Blueprint: /voice_changer/*
Handles:  start/stop live stream  •  short recording (0.001-3 s)
          Emits “voice_frame” chunks over Socket.IO to the browser.
"""
import os, queue, time, io, wave, threading
from flask import Blueprint, jsonify, request
import numpy as np
voice_bp = Blueprint("voice_changer", __name__, url_prefix="/api")

stream_thread = None
stream_event = threading.Event()

@voice_bp.route('/start', methods=['POST'])
def start():
    global stream_thread
    if stream_thread and stream_thread.is_alive():
        return jsonify({"status": "Already running"})
    stream_event.clear()
    stream_thread = threading.Thread(target=start_audio_stream, args=(stream_event,), daemon=True)
    stream_thread.start()
    return jsonify({"status": "Started"})

@voice_bp.route('/stop', methods=['POST'])
def stop():
    stream_event.set()
    return jsonify({"status": "Stopped"})

@voice_bp.route('/record', methods=['POST'])
def record():
    action = request.json.get("action")
    with data_lock:
        if action == "start":
            params.is_recording = True
            params.recorded_data = []
            return jsonify({"status": "Recording started"})
        elif action == "stop":
            params.is_recording = False
            return jsonify({"status": "Recording stopped"})
    return jsonify({"status": "Invalid action"}), 400

@voice_bp.route('/playback', methods=['GET'])
def playback():
    return jsonify({"status": "Not implemented"})

@voice_bp.route('/tuner', methods=['POST'])
def update_tuner():
    """
    Accepts a JSON payload like:
    {
        "pitch_shift": 2,
        "volume_multiplier": 1.5,
        "speed_rate": 1.2
    }
    """
    try:
        effects = request.json
        update_effects(effects)
        return jsonify({"status": "Updated effects", "effects": effects})
    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500
