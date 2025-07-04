import json, threading, pathlib, tkinter as tk
from   tkinter import ttk, filedialog, messagebox
from   typing   import Optional

import numpy as np
import sounddevice as sd
from   scipy.signal import butter, lfilter
import librosa

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from   matplotlib.figure import Figure
from   matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from   flask import Flask, request, jsonify
from   flask_cors import CORS

# ── audio constants ────────────────────────────────────────────────────────────
FS_DEF    = 44_100
BLOCK_DEF = 1_024
CH        = 1
MIN_SEC   = 0.001
MAX_SEC   = 3.0

# ── shared state object ────────────────────────────────────────────────────────
class Params:
    # FX sliders
    pitch_shift   = 0.0
    volume        = 1.0
    speed         = 1.0
    eq_bands      = [0.0]*5
    echo          = 0.0
    reverb        = 0.0
    chorus        = 0.0
    compression   = 0.0
    noise_gate    = 0.0
    # toggles
    en_pitch      = True
    en_speed      = True
    en_eq         = True
    en_echo       = True
    en_reverb     = True
    en_chorus     = True
    en_comp       = True
    en_gate       = True
    master_bypass = False
    # runtime
    block_size    = BLOCK_DEF
    in_dev        = None
    out_dev       = None
    update_plot   = False
    plot_data     = np.zeros(BLOCK_DEF, np.float32)
    is_recording  = False
    recorded_data = []
    input_level   = 0.0                 # RMS for meter

P          = Params()
LOCK       = threading.Lock()
ECHO_BUF   = np.zeros(FS_DEF*2, np.float32)
ECHO_IDX   = 0

# ── helper wrappers ────────────────────────────────────────────────────────────
def enable(flag, fn, x, *a):           # tiny conditional
    return fn(x, *a) if flag else x

def safe_pitch(x, n, sr):
    if n == 0: return x
    try:
        return librosa.effects.pitch_shift(x, n_steps=n, sr=sr,
                                           n_fft=min(len(x), 1024))
    except TypeError:                  # librosa <0.10
        return librosa.effects.pitch_shift(x, sr, n,
                                           n_fft=min(len(x), 1024))

def safe_stretch(x, r):
    if r == 1.0: return x
    try:
        return librosa.effects.time_stretch(x, rate=r)
    except Exception as e:
        print("Time-stretch error:", e)
        return x

def apply_eq(x, g):
    if not any(g): return x
    bands = [(20, 250), (250, 500), (500, 2e3), (2e3, 4e3), (4e3, 2e4)]
    y = np.zeros_like(x)
    for gain, (lo, hi) in zip(g, bands):
        if gain == 0: continue
        b, a = butter(2, [lo/(FS_DEF/2), hi/(FS_DEF/2)], btype='band')
        y += lfilter(b, a, x) * (10**(gain/20))
    return x + y

def apply_reverb(x, a):
    if a <= 0: return x
    ir = np.exp(-a*np.arange(len(x))/FS_DEF)
    return x + np.convolve(x, ir)[:len(x)]

def apply_chorus(x, a):
    if a <= 0: return x
    depth = a * 0.002
    f     = 0.25
    t     = np.arange(len(x))/FS_DEF
    delayed = np.interp(t - depth*np.sin(2*np.pi*f*t), t, x, left=0, right=0)
    return x + delayed

def apply_comp(x, a):
    if a <= 0: return x
    th, ratio = 0.5, 1 + a*4
    y = x.copy()
    m = np.abs(x) > th
    y[m] = np.sign(x[m]) * (th + (np.abs(x[m]) - th) / ratio)
    return y

def apply_gate(x, th):
    return np.where(np.abs(x) < th, 0, x) if th > 0 else x

def apply_echo(x, d):
    global ECHO_IDX
    if d <= 0: return x
    delay = min(int(d * FS_DEF), len(ECHO_BUF) - 1)
    y = x.copy()
    for i in range(len(x)):
        idx = (ECHO_IDX - delay + len(ECHO_BUF)) % len(ECHO_BUF)
        y[i] += 0.5 * ECHO_BUF[idx]
        ECHO_BUF[ECHO_IDX] = x[i]
        ECHO_IDX = (ECHO_IDX + 1) % len(ECHO_BUF)
    return y

# ── PortAudio callback ─────────────────────────────────────────────────────────
def audio_cb(indata, outdata, frames, _, status):
    if status: print(status)
    x = indata[:, 0].astype(np.float32)

    with LOCK: p = P

    # store input level (RMS)
    p.input_level = float(np.sqrt(np.mean(x**2)))

    if p.master_bypass:
        outdata[:] = x.reshape(-1, 1)
        return

    try:
        x = enable(p.en_gate,   apply_gate,   x, p.noise_gate)
        x = enable(p.en_pitch,  safe_pitch,   x, p.pitch_shift, FS_DEF)
        x = enable(p.en_speed,  safe_stretch, x, p.speed)

        # force frame length
        if len(x) > frames:
            x = x[:frames]
        elif len(x) < frames:
            x = np.pad(x, (0, frames-len(x)))

        x = enable(p.en_eq,     apply_eq,     x, p.eq_bands)
        x = enable(p.en_reverb, apply_reverb, x, p.reverb)
        x = enable(p.en_chorus, apply_chorus, x, p.chorus)
        x = enable(p.en_comp,   apply_comp,   x, p.compression)
        x = enable(p.en_echo,   apply_echo,   x, p.echo)

        x *= p.volume
        x = np.clip(x, -1, 1)
    except Exception as e:
        print("DSP error:", e)

    with LOCK:
        if p.is_recording:
            p.recorded_data.append(x.copy())
        if p.update_plot:
            p.plot_data = x.copy()

    outdata[:] = x.reshape(-1, 1)

# ── stream management ──────────────────────────────────────────────────────────
stream_evt = threading.Event()
stream_th: Optional[threading.Thread] = None

def stream_worker(ev):
    while not ev.is_set():
        try:
            with sd.Stream(
                    samplerate=FS_DEF,
                    blocksize=P.block_size,
                    device=(P.in_dev, P.out_dev),
                    channels=1,
                    dtype='float32',
                    callback=audio_cb):
                ev.wait()
        except Exception as e:
            print("Stream error:", e)
            sd.sleep(500)

def audio_start():
    global stream_th
    if stream_th and stream_th.is_alive():
        return "running"
    stream_evt.clear()
    stream_th = threading.Thread(target=stream_worker, args=(stream_evt,), daemon=True)
    stream_th.start()
    return "started"

def audio_stop():
    if stream_evt.is_set():
        return "already"
    stream_evt.set()
    return "stopped"

# ── Flask API (optional) ───────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.route('/api/start', methods=['POST'])
def api_start():  return jsonify(status=audio_start())

@app.route('/api/stop', methods=['POST'])
def api_stop():   return jsonify(status=audio_stop())

@app.route('/api/params', methods=['POST'])
def api_params():
    data = request.json or {}
    with LOCK:
        for k, v in data.items():
            if hasattr(P, k):
                setattr(P, k, v)
    return jsonify(status="ok")

# ── preset helpers ─────────────────────────────────────────────────────────────
PRESET_PATH = pathlib.Path("last_preset.json")

def save_last_preset():
    with LOCK:
        d = {k: v for k, v in P.__dict__.items() if not k.startswith("_")}
    try:
        PRESET_PATH.write_text(json.dumps(d, indent=2))
    except Exception as e:
        print("Preset save error:", e)

def load_last_preset():
    if not PRESET_PATH.exists():
        return
    try:
        d = json.loads(PRESET_PATH.read_text())
        with LOCK:
            for k, v in d.items():
                if hasattr(P, k):
                    setattr(P, k, v)
        print("Loaded last preset.")
    except Exception as e:
        print("Preset load error:", e)

# ── GUI builder ────────────────────────────────────────────────────────────────
def build_gui():
    root = tk.Tk()
    root.title("Voice-Changer Tuner")

    # status LED -----------------------------------------------------------------
    led = tk.Label(root, width=2, relief="sunken", bg="red")
    led.grid(row=0, column=0, sticky="w", padx=5, pady=4)

    def led_set(on: bool):
        led.config(bg="green" if on else "red")

    # device pickers -------------------------------------------------------------
    devs = sd.query_devices()
    in_list  = [f"{i}: {d['name']}" for i, d in enumerate(devs) if d['max_input_channels']]
    out_list = [f"{i}: {d['name']}" for i, d in enumerate(devs) if d['max_output_channels']]
    P.in_dev, P.out_dev = sd.default.device

    frm_io = ttk.LabelFrame(root, text="Audio Devices", padding=6)
    frm_io.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
    ttk.Label(frm_io, text="Input").grid(row=0, column=0, sticky="w")
    cb_in = ttk.Combobox(frm_io, values=in_list, state="readonly", width=40)
    cb_in.set(f"{P.in_dev}: {devs[P.in_dev]['name']}")
    cb_in.grid(row=0, column=1, sticky="ew")
    ttk.Label(frm_io, text="Output").grid(row=1, column=0, sticky="w")
    cb_out = ttk.Combobox(frm_io, values=out_list, state="readonly", width=40)
    cb_out.set(f"{P.out_dev}: {devs[P.out_dev]['name']}")
    cb_out.grid(row=1, column=1, sticky="ew")

    def set_dev(*_):
        P.in_dev  = int(cb_in.get().split(":")[0])
        P.out_dev = int(cb_out.get().split(":")[0])

    cb_in.bind("<<ComboboxSelected>>", set_dev)
    cb_out.bind("<<ComboboxSelected>>", set_dev)

    # block size selector
    ttk.Label(frm_io, text="Block").grid(row=2, column=0, sticky="w")
    cb_blk = ttk.Combobox(frm_io, values=[256, 512, 1024, 2048], state="readonly", width=6)
    cb_blk.set(P.block_size)
    cb_blk.grid(row=2, column=1, sticky="w")
    cb_blk.bind("<<ComboboxSelected>>", lambda *_: setattr(P, "block_size", int(cb_blk.get())))

    # start / stop buttons -------------------------------------------------------
    frm_btn = ttk.Frame(root)
    frm_btn.grid(row=2, column=0, sticky="ew")
    b_start = ttk.Button(frm_btn, text="Start")
    b_stop  = ttk.Button(frm_btn, text="Stop", state="disabled")
    b_start.pack(side="left", padx=3)
    b_stop.pack(side="left", padx=3)

    bypass = tk.BooleanVar()
    ttk.Checkbutton(frm_btn, text="Master Bypass", variable=bypass,
                    command=lambda: setattr(P, "master_bypass", bypass.get())
                    ).pack(side="left", padx=10)

    def gui_start():
        b_start.config(state="disabled")
        b_stop.config(state="normal")
        P.update_plot = True
        led_set(True)
        audio_start()

    def gui_stop():
        b_stop.config(state="disabled")
        b_start.config(state="normal")
        P.update_plot = False
        led_set(False)
        audio_stop()

    b_start.config(command=gui_start)
    b_stop.config(command=gui_stop)

    # FX rack --------------------------------------------------------------------
    rack = ttk.LabelFrame(root, text="FX Rack", padding=6)
    rack.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
    root.columnconfigure(0, weight=1)
    rack.columnconfigure(1, weight=1)

    def add_slider(r, label, lo, hi, res, attr, en_var=None):
        ttk.Label(rack, text=label).grid(row=r, column=0, sticky="w")
        s = tk.Scale(rack, from_=lo, to=hi, resolution=res,
                     orient=tk.HORIZONTAL, length=240,
                     command=lambda v, a=attr: setattr(P, a, float(v)))
        s.set(getattr(P, attr))
        s.grid(row=r, column=1, sticky="ew")
        if en_var is not None:
            tk.Checkbutton(rack, variable=en_var).grid(row=r, column=2)
        return s

    vars_en = {k: tk.BooleanVar(value=True) for k in
               ("pitch", "speed", "eq", "echo", "reverb", "chorus", "comp", "gate")}

    def bind_en(var, attr): var.trace_add("write", lambda *_: setattr(P, attr, var.get()))
    bind_en(vars_en["pitch"],  "en_pitch")
    bind_en(vars_en["speed"],  "en_speed")
    bind_en(vars_en["eq"],     "en_eq")
    bind_en(vars_en["echo"],   "en_echo")
    bind_en(vars_en["reverb"], "en_reverb")
    bind_en(vars_en["chorus"], "en_chorus")
    bind_en(vars_en["comp"],   "en_comp")
    bind_en(vars_en["gate"],   "en_gate")

    add_slider(0, "Pitch (semi)", -12, 12, 0.1, "pitch_shift", vars_en["pitch"])
    add_slider(1, "Speed",         0.5,  2,  0.05, "speed",      vars_en["speed"])
    add_slider(2, "Volume",        0,    2,  0.05, "volume")
    add_slider(3, "Noise Gate",    0, 0.1,  0.005, "noise_gate", vars_en["gate"])
    add_slider(4, "Echo (s)",      0,    2,  0.05, "echo",       vars_en["echo"])
    add_slider(5, "Reverb",        0,    1,  0.05, "reverb",     vars_en["reverb"])
    add_slider(6, "Chorus",        0,    1,  0.05, "chorus",     vars_en["chorus"])
    add_slider(7, "Compression",   0,    1,  0.05, "compression",vars_en["comp"])

    # 5-band EQ
    eqfrm = ttk.Frame(rack)
    eqfrm.grid(row=8, column=0, columnspan=3, pady=4)
    eqnames = ["Sub", "Bass", "Mid", "HiMid", "Treble"]
    def set_eq(i, v): P.eq_bands[i] = float(v)
    for i, n in enumerate(eqnames):
        tk.Scale(eqfrm, label=n, from_=-12, to=12, resolution=0.5,
                 orient=tk.VERTICAL, length=150,
                 command=lambda v, i=i: set_eq(i, v)
                 ).grid(row=0, column=i, padx=2)

    # wave / spectrum plot -------------------------------------------------------
    fig = Figure(figsize=(5,2.2), dpi=100)
    ax  = fig.add_subplot(111)
    line, = ax.plot(np.zeros(BLOCK_DEF))
    ax.set_ylim(-1, 1)
    ax.set_xlim(0, BLOCK_DEF)
    ax.set_title("Waveform")

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().grid(row=1, column=1, rowspan=3, sticky="nsew")
    root.grid_columnconfigure(1, weight=1)

    # RMS meter ------------------------------------------------------------------
    lvl = ttk.Progressbar(root, length=120, maximum=0.25, mode="determinate")
    lvl.grid(row=0, column=1, sticky="e", padx=8)

    # toggle plot mode
    spec = [False]
    def toggle():
        spec[0] = not spec[0]
        ax.cla()
        if spec[0]:
            ax.set_title("Spectrum")
            ax.set_ylim(-120, 0)
            ax.set_xlabel("Hz")
        else:
            ax.set_title("Waveform")
            ax.set_ylim(-1, 1)
            ax.set_xlabel("samples")
    tk.Button(root, text="Scope ▸ Spectrum", command=toggle
              ).grid(row=4, column=1, sticky="e", padx=4, pady=3)

    # periodic UI refresh
    def refresh():
        if P.update_plot:
            with LOCK: d = P.plot_data.copy(); level = P.input_level
            lvl["value"] = level
            if spec[0]:
                m  = np.abs(np.fft.rfft(d * np.hanning(len(d)))) + 1e-12
                db = 20 * np.log10(m / m.max())
                f  = np.fft.rfftfreq(len(d), 1/FS_DEF)
                line.set_data(f, db)
                ax.set_xlim(0, FS_DEF/2)
                ax.set_ylim(-120, 0)
            else:
                line.set_data(range(len(d)), d)
                ax.set_xlim(0, len(d))
                ax.set_ylim(-1, 1)
            canvas.draw_idle()
        root.after(40, refresh)
    refresh()

    # record / playback ----------------------------------------------------------
    rec_b     = ttk.Button(root, text="Record")
    stoprec_b = ttk.Button(root, text="Stop Rec", state="disabled")
    play_b    = ttk.Button(root, text="Play")
    rec_b.grid(row=5, column=0, pady=4)
    stoprec_b.grid(row=5, column=1, pady=4, sticky="w")
    play_b.grid(row=5, column=1, pady=4, sticky="e")

    def rec_start():
        rec_b.config(state="disabled")
        stoprec_b.config(state="normal")
        with LOCK:
            P.recorded_data.clear()
            P.is_recording = True

    def rec_stop():
        stoprec_b.config(state="disabled")
        rec_b.config(state="normal")
        P.is_recording = False

    def play():
        with LOCK:
            if not P.recorded_data:
                return
            buf = np.concatenate(P.recorded_data)

        min_samples = int(MIN_SEC * FS_DEF)
        max_samples = int(MAX_SEC * FS_DEF)
        if len(buf) < min_samples:
            print("Recording too short – padding.")
            buf = np.pad(buf, (0, min_samples - len(buf)), 'constant')
        elif len(buf) > max_samples:
            print("Recording too long – trimming.")
            buf = buf[:max_samples]

        def cb(outdata, frames, _, __):
            nonlocal buf
            take = min(frames, len(buf))
            outdata[:take, 0] = buf[:take]
            outdata[take:] = 0
            buf = buf[take:]
            if len(buf) == 0:
                raise sd.CallbackStop

        with sd.OutputStream(device=P.out_dev,
                             channels=1,
                             samplerate=FS_DEF,
                             callback=cb):
            sd.sleep(int(len(buf) / FS_DEF * 1000) + 100)

    rec_b.config(command=rec_start)
    stoprec_b.config(command=rec_stop)
    play_b.config(command=play)

    # preset save / load ---------------------------------------------------------
    def save_p():
        fn = filedialog.asksaveasfilename(defaultextension=".json")
        if not fn:
            return
        with LOCK:
            d = {k: v for k, v in P.__dict__.items() if not k.startswith("_")}
        pathlib.Path(fn).write_text(json.dumps(d, indent=2))

    def load_p():
        fn = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not fn:
            return
        try:
            d = json.loads(pathlib.Path(fn).read_text())
            with LOCK:
                for k, v in d.items():
                    if hasattr(P, k):
                        setattr(P, k, v)
            messagebox.showinfo("Preset", "Loaded (sliders update on restart).")
        except Exception as e:
            messagebox.showerror("Preset", str(e))

    ttk.Button(root, text="Save Preset", command=save_p
               ).grid(row=6, column=0, pady=3)
    ttk.Button(root, text="Load Preset", command=load_p
               ).grid(row=6, column=1, pady=3, sticky="w")

    # graceful exit --------------------------------------------------------------
    def on_close():
        save_last_preset()
        gui_stop()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    # auto-restore last settings
    load_last_preset()
    return root, led_set

# ── runner ──────────────────────────────────────────────────────────────────────
def main():
    # run Flask in background ----------------------------------------------------
    threading.Thread(target=lambda: app.run(port=5000), daemon=True).start()
    gui, _ = build_gui()
    gui.mainloop()

if __name__ == "__main__":
    main()
