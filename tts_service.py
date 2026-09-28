#!/usr/bin/env python3
"""
Keyboard-driven TTS bridge for ComfyUI.

Runs in the background and exposes five actions:

    G1 -> /start        begin recording the mic (keeps going until render)
    G2 -> /render       stop recording, run the workflow, hold the result
                        press again to re-roll the same recording
    G3 -> /passthrough  toggle the real mic straight through to the cable
    G4 -> /cancel       stop a stuck generation
    G5 -> /play         play the held result to VB-Cable (repeatable)

Start it with:  python tts_service.py

Config is at the top. Edit once and forget it.
"""

import json
import io
import os
import sys
import time
import copy
import queue
import random
import shutil
import threading
import urllib.request
import uuid
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import sounddevice as sd
import soundfile as sf

# ---------------------------------------------------------------- config

COMFY_URL = "http://127.0.0.1:8188"

# Your workflow exported via: Workflow -> Export (API)
# Your workflow exported via: Workflow -> Export (API).
# Looked for next to this script, so the folder stays portable.
WORKFLOW_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflow_api.json"
)

# ComfyUI's input folder. Recordings and voice copies get written here.
# THIS IS THE ONE PATH YOU MUST EDIT when moving to another machine.
COMFY_INPUT_DIR = r"C:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI\input"

# Recordings are named ptt_<timestamp>.wav so ComfyUI never serves a
# cached result for a stale file of the same name.
RECORDING_PREFIX = "ptt_"

# Old recordings are deleted once there are more than this many.
KEEP_RECORDINGS = 20

# Playback device. Partial name match, or an integer index.
OUTPUT_DEVICE = "CABLE Input"

# Recording device. None = Windows default microphone.
# If mic.txt exists in this folder, its contents override this setting,
# which lets the mic_*.bat files switch mics without a restart.
INPUT_DEVICE = None

MIC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mic.txt")

# Node holding the reference voice being cloned. None = auto-detect the
# audio loader that isn't AUDIO_INPUT_NODE. If voice.txt exists, its
# contents set which file that node loads.
REFERENCE_NODE = None

VOICE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice.txt")

# Your voice library. Reference clips live here, not in ComfyUI's input
# folder. The selected one is copied across automatically at render time.
VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")

# Copies land in ComfyUI's input folder under this prefix.
VOICE_PREFIX = "tts_voice_"

# Where ComfyUI writes preview renders. None works it out from
# COMFY_INPUT_DIR, which is usually right for a standard install.
CLEAN_TEMP_DIR = None

RECORD_SAMPLERATE = 44100   # preferred; the driver may force something else
RECORD_CHANNELS = 1

# Node that loads the recorded audio. None = auto-detect.
AUDIO_INPUT_NODE = "41"

# Breeze Voice Direction node that receives the generated instruction.
# None = auto-detect. Set to False to turn prosody matching off entirely.
INSTRUCTION_NODE = None

# Extra wording appended to every generated instruction. Leave blank
# for none, e.g. "Scottish accent, natural delivery".
INSTRUCTION_SUFFIX = ""

LISTEN_PORT = 8765

# If a render comes back near-silent (the Breeze stall bug), throw it away
# and try again rather than handing you a clip of nothing.
RETRY_ON_SILENCE = 2
SILENCE_THRESHOLD_DB = -45

# Identifies our jobs to ComfyUI so they appear in its queue panel and can
# be cancelled from the browser as well as from the cancel key.
# Match output audio to the cable's sample rate before playing.
# Breeze renders at 24kHz; VB-Cable usually runs at 48kHz. Toggle at
# runtime from the panel or /resample to compare.
RESAMPLE_OUTPUT = True

# Play each finished render immediately, as if the play key was pressed.
# Toggle at runtime from the panel or /autoplay.
AUTOPLAY = False

# Playback boost for loud games. Each entry is (label, extra dB after
# normalising to -1 dBFS). None means leave the audio untouched.
BOOST_MODES = [
    ("OFF", None),
    ("Normalize", 0.0),
    ("Boost +6", 6.0),
    ("Boost +12", 12.0),
]
BOOST_DEFAULT = 0

# cfg_scale override, cycled from the panel. None uses whatever the
# workflow has set. 1.0 clones the reference closely; higher values push
# away from it, which flattens emotional swings and reads more neutral.
CFG_CHOICES = [None, 1.0, 2.0, 3.0, 4.0]
CFG_DEFAULT = 0

# Local monitor: plays the clip on your own headphones as well as the
# cable, so you can hear it over a loud game. The Volume setting applies
# ONLY to this copy - the cable feed is always sent as rendered.
# None uses your Windows default output device.
MONITOR_DEVICE = None
MONITOR_ENABLED = False

CLIENT_ID = str(uuid.uuid4())

MAX_RECORD_SECONDS = 120
GENERATION_TIMEOUT = 180

# ------------------------------------------------------------- internals

_frames = []
_stream = None
_recording = False         # True whether via its own stream or the bridge
_warned_busy = False       # stops repeat-while-holding macros flooding the log
_our_renders = set()       # (subfolder, filename) of renders we fetched
_pt_rate = None            # samplerate the passthrough bridge negotiated
_lock = threading.Lock()
_rendering = False
_last_clip = None          # raw bytes of the most recent generation
_last_recording = None     # filename of the most recent capture
_last_instruction = None   # delivery instruction from the last capture
_cancelled = False         # set by the cancel key to abort a render
_record_rate = RECORD_SAMPLERATE   # rate the driver actually gave us
_passthrough = False       # True = real mic is bridged to the cable
_suspend_passthrough = False   # muted briefly while a clip plays
_resample_enabled = RESAMPLE_OUTPUT   # runtime toggle for output resampling
_autoplay = AUTOPLAY                  # runtime toggle for automatic playback
_boost_index = BOOST_DEFAULT          # index into BOOST_MODES
_cfg_index = CFG_DEFAULT              # index into CFG_CHOICES
_monitor_enabled = MONITOR_ENABLED    # local headphone monitor
_pt_in = None              # mic stream for the bridge
_pt_out = None             # cable stream for the bridge
_pt_buf = None             # ring buffer between them
_playback_lock = threading.Lock()
_pt_lock = threading.Lock()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def api(path, payload=None):
    url = f"{COMFY_URL}{path}"
    if payload is None:
        req = urllib.request.Request(url)
    else:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    if not body.strip():
        return {}          # /interrupt and friends return nothing
    try:
        return json.loads(body)
    except ValueError:
        return {}


# ------------------------------------------------------------- recording

HOSTAPI_PREFERENCE = {
    "mme": 0,
    "windows directsound": 1,
    "windows wasapi": 2,
    "windows wdm-ks": 3,
    "asio": 4,
}


def hostapi_name(index):
    try:
        info = sd.query_devices(index)
        return sd.query_hostapis(info["hostapi"])["name"]
    except Exception:
        return "?"


def refresh_devices():
    """Re-enumerate audio devices.

    PortAudio builds its device list once at startup and caches it. If
    Windows changes the default recording device, its MME device IDs are
    reordered underneath us - the cached list keeps the old names while
    the indices now point somewhere else, which shows up as a correctly
    named device recording silence. Re-initialising rebuilds the list.

    Only safe when no streams are open, so it is a no-op otherwise.
    """
    if _stream is not None or _pt_in is not None:
        return False
    try:
        sd._terminate()
        sd._initialize()
        return True
    except Exception as exc:
        log(f"device refresh failed: {exc}")
        return False


def base_device_name(name):
    """'MAIN (MAIN (RC-505mk2))' -> 'main'. Windows names the same input
    differently per audio API, so compare on the part before the bracket."""
    return str(name).split("(")[0].strip().lower()


def input_device_candidates(name):
    """Every input device that could be this mic, best host API first.

    Windows exposes the same physical interface once per audio API, under
    slightly different names. Some of those entries (WDM-KS especially)
    refuse to open, so collect exact matches first and then widen to other
    entries for the same underlying device.
    """
    if name is None:
        return [None]
    if isinstance(name, int) or str(name).isdigit():
        return [int(name)]

    needle = str(name).lower()
    devices = list(enumerate(sd.query_devices()))
    inputs = [(i, d) for i, d in devices if d["max_input_channels"] > 0]

    exact = [i for i, d in inputs if needle in d["name"].lower()]

    # Widen: other entries whose base name matches, e.g. the MME and
    # WASAPI versions of a device we only matched under WDM-KS.
    wanted_base = base_device_name(name)
    widened = [
        i for i, d in inputs
        if i not in exact and base_device_name(d["name"]) == wanted_base
    ]

    if not exact and not widened:
        raise RuntimeError(f"no input device matching '{name}'")

    def rank(i):
        return HOSTAPI_PREFERENCE.get(hostapi_name(i).lower(), 9)

    return sorted(exact, key=rank) + sorted(widened, key=rank)


def to_float_mono(indata):
    """Normalise whatever the driver hands us to mono float64."""
    data = np.asarray(indata)
    if data.dtype.kind == "i":
        data = data.astype(np.float64) / float(np.iinfo(data.dtype).max + 1)
    else:
        data = data.astype(np.float64)
    if data.ndim == 1:
        return data.reshape(-1, 1)
    if data.shape[1] > 1:
        return data.mean(axis=1, keepdims=True)
    return data


def open_input_stream(devices, callback, prefer_rate=None, block_seconds=None):
    """Open a mic stream, negotiating a device and format the driver accepts.

    `devices` is a list of candidate indices. Works through each device,
    then each plausible rate/channel/format combination, and takes the
    first that actually opens.

    Returns (stream, samplerate, channels, device_index).
    """
    if not isinstance(devices, (list, tuple)):
        devices = [devices]

    last_error = None
    tried = 0

    for device in devices:
        try:
            info = sd.query_devices(device if device is not None else sd.default.device[0])
        except Exception:
            info = {}

        dev_rate = int(info.get("default_samplerate") or 0)
        max_ch = int(info.get("max_input_channels") or 1) or 1

        rates = [r for r in dict.fromkeys([prefer_rate, dev_rate, 48000, 44100]) if r]
        channels = [c for c in dict.fromkeys([1, min(2, max_ch), max_ch]) if 0 < c <= max_ch]
        dtypes = ["float32", "int16", "int32"]

        for rate in rates:
            for chan in channels:
                for dtype in dtypes:
                    kwargs = {
                        "samplerate": rate,
                        "channels": chan,
                        "device": device,
                        "callback": callback,
                        "dtype": dtype,
                    }
                    if block_seconds:
                        kwargs["blocksize"] = int(rate * block_seconds)
                    tried += 1
                    try:
                        stream = sd.InputStream(**kwargs)
                        stream.start()
                        log(f"  mic: [{device}] {hostapi_name(device)} "
                            f"{rate} Hz, {chan}ch, {dtype}")
                        return stream, rate, chan, device
                    except Exception as exc:
                        last_error = exc

    raise RuntimeError(
        f"could not open microphone after {tried} attempts "
        f"across {len(devices)} device(s) - {last_error}. "
        "Run: python tts_service.py --probe"
    )


def start_passthrough():
    """Bridge the real mic straight through to the virtual cable.

    Lets the user talk normally in games that can't change input device
    without a restart. Muted automatically while recording a TTS line or
    while a generated clip is playing.
    """
    global _pt_in, _pt_out, _pt_buf, _passthrough, _pt_rate

    with _pt_lock:
        if _pt_in is not None:
            return True

        refresh_devices()

        try:
            out_idx = resolve_device(OUTPUT_DEVICE)
            in_candidates = input_device_candidates(current_input_setting())
        except RuntimeError as exc:
            log(f"passthrough failed: {exc}")
            return False

        rate = device_samplerate(out_idx) or 48000
        block = int(rate * 0.02)          # 20ms blocks
        _pt_buf = queue.Queue(maxsize=32)

        def on_input(indata, frames, time_info, status):
            mono = to_float_mono(indata)
            if _recording:
                _frames.append(mono)      # recording shares this stream
                return                    # and its audio never reaches the cable
            if _suspend_passthrough:
                return                    # muted while a clip plays
            try:
                _pt_buf.put_nowait(mono.astype(np.float32))
            except queue.Full:
                pass                      # drop rather than build latency

        def on_output(outdata, frames, time_info, status):
            try:
                chunk = _pt_buf.get_nowait()
            except queue.Empty:
                outdata.fill(0)
                return
            count = min(len(chunk), frames)
            outdata[:count] = chunk[:count]
            if count < frames:
                outdata[count:].fill(0)

        try:
            _pt_in, in_rate, _, _ = open_input_stream(
                in_candidates, on_input, prefer_rate=rate, block_seconds=0.02
            )
            _pt_rate = in_rate
            if in_rate != rate:
                log(f"  mic runs at {in_rate} Hz, cable at {rate} Hz - using {in_rate}")
                rate = in_rate
                block = int(rate * 0.02)

            _pt_out = sd.OutputStream(
                samplerate=rate, blocksize=block, channels=1,
                device=out_idx, callback=on_output, dtype="float32",
            )
            _pt_out.start()
        except Exception as exc:
            log(f"passthrough failed: {exc}")
            stop_passthrough()
            return False

    _passthrough = True
    log("PASSTHROUGH ON - your real voice goes to the cable")
    return True


def stop_passthrough():
    global _pt_in, _pt_out, _pt_buf, _passthrough

    with _pt_lock:
        for stream in (_pt_in, _pt_out):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        _pt_in = None
        _pt_out = None
        _pt_buf = None

    if _passthrough:
        log("PASSTHROUGH OFF - only generated voice goes to the cable")
    _passthrough = False


def toggle_autoplay():
    global _autoplay
    _autoplay = not _autoplay
    log(f"autoplay {'ON' if _autoplay else 'OFF'}")
    return _autoplay


def toggle_resample():
    global _resample_enabled
    _resample_enabled = not _resample_enabled
    log(f"resample {'ON' if _resample_enabled else 'OFF'}")
    return _resample_enabled


def toggle_passthrough():
    if _passthrough:
        stop_passthrough()
    else:
        start_passthrough()
    return _passthrough


def start_recording():
    global _stream, _frames, _record_rate, _recording, _warned_busy

    with _lock:
        if _rendering:
            # Repeat-while-holding macros fire this continuously, so say
            # it once rather than flooding the log.
            if not _warned_busy:
                log("busy rendering, ignoring")
                _warned_busy = True
            return
        if _recording:
            if not _warned_busy:
                log("already recording")
                _warned_busy = True
            return
        _warned_busy = False
        _frames = []

        # If the passthrough bridge already holds the mic, tap into it.
        # Opening a second stream on the same device returns silence.
        if _passthrough and _pt_in is not None:
            _record_rate = _pt_rate or RECORD_SAMPLERATE
            _recording = True
            log(f"RECORDING [via passthrough, {_record_rate} Hz] "
                "- press your render key when done")
            return

        def cb(indata, frames, time_info, status):
            if status:
                log(f"audio status: {status}")
            _frames.append(to_float_mono(indata))

        refresh_devices()

        setting = current_input_setting()
        try:
            candidates = input_device_candidates(setting)
        except RuntimeError as exc:
            log(f"ERROR: {exc}")
            return

        try:
            _stream, _record_rate, _, device_index = open_input_stream(
                candidates, cb, prefer_rate=RECORD_SAMPLERATE
            )
        except Exception as exc:
            log(f"ERROR: {exc}")
            _stream = None
            return

        _recording = True

    label = sd.query_devices(device_index)["name"] if device_index is not None else "default"
    log(f"RECORDING [{label}] - press your render key when done")


TOO_SHORT = object()


class Cancelled(Exception):
    """Raised when the user hits the cancel key mid-render."""


def stop_recording():
    """Stop capture and write the wav.

    Returns the new filename, None if we weren't recording at all,
    or TOO_SHORT if the capture was unusable.
    """
    global _stream, _recording

    with _lock:
        if not _recording:
            return None
        _recording = False
        if _stream is not None:
            _stream.stop()
            _stream.close()
            _stream = None
        chunks = _frames[:]

    if not chunks:
        log("nothing captured")
        return TOO_SHORT

    audio = np.concatenate(chunks, axis=0)
    seconds = len(audio) / _record_rate

    if seconds < 0.3:
        log(f"too short ({seconds:.2f}s), ignoring")
        return TOO_SHORT
    if seconds > MAX_RECORD_SECONDS:
        audio = audio[: int(MAX_RECORD_SECONDS * _record_rate)]
        seconds = MAX_RECORD_SECONDS
        log(f"trimmed to {MAX_RECORD_SECONDS}s")

    global _last_recording

    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    name = f"{RECORDING_PREFIX}{int(time.time() * 1000)}.wav"
    path = os.path.join(COMFY_INPUT_DIR, name)
    sf.write(path, audio, _record_rate)
    peak = float(np.abs(audio).max())
    peak_db = 20 * np.log10(peak) if peak > 0 else -999

    _last_recording = name
    prune_recordings()

    if peak_db < -45:
        log(f"captured {seconds:.2f}s - WARNING: near-silent (peak {peak_db:.0f} dBFS)")
        log("  the wrong input device is probably selected")
        log("  run: python tts_service.py --inputs")
    else:
        log(f"captured {seconds:.2f}s (peak {peak_db:.0f} dBFS)")

    return name


def prune_recordings():
    """Delete the oldest recordings so the input folder doesn't grow forever."""
    try:
        files = [
            f for f in os.listdir(COMFY_INPUT_DIR)
            if f.startswith(RECORDING_PREFIX) and f.endswith(".wav")
        ]
        for old in sorted(files)[:-KEEP_RECORDINGS]:
            os.remove(os.path.join(COMFY_INPUT_DIR, old))
    except OSError:
        pass


# -------------------------------------------------------------- workflow

LOADER_HINTS = ("loadaudio", "load_audio", "loadaudiofrompath")


def comfy_temp_dir():
    """Where ComfyUI writes preview renders. Sibling of the input folder."""
    if CLEAN_TEMP_DIR:
        return CLEAN_TEMP_DIR
    return os.path.join(os.path.dirname(COMFY_INPUT_DIR.rstrip("\\/")), "temp")


def cleanup_generated():
    """Delete the files this tool has generated.

    Three groups, all disposable:
      - ptt_*.wav recordings in ComfyUI's input folder
      - tts_voice_* copies of reference clips (re-copied automatically)
      - audio renders in ComfyUI's temp folder

    Refuses while a render is in flight, since those files are in use.
    """
    if _rendering:
        log("busy rendering - try again in a moment")
        return {"deleted": 0, "bytes": 0, "skipped": True}

    deleted = 0
    freed = 0

    def purge(folder, match, label):
        nonlocal deleted, freed
        count = 0
        size = 0
        try:
            entries = os.listdir(folder)
        except OSError:
            return
        for entry in entries:
            path = os.path.join(folder, entry)
            if not os.path.isfile(path) or not match(entry):
                continue
            try:
                size += os.path.getsize(path)
                os.remove(path)
                count += 1
            except OSError:
                pass
        if count:
            log(f"  removed {count} {label} ({size / 1048576:.1f} MB)")
        deleted += count
        freed += size

    purge(COMFY_INPUT_DIR,
          lambda f: f.startswith(RECORDING_PREFIX) and f.lower().endswith(".wav"),
          "recordings")

    purge(COMFY_INPUT_DIR,
          lambda f: f.startswith(VOICE_PREFIX),
          "voice copies")

    # Only our own renders, tracked by filename as they were fetched.
    # Other workflows also write audio into ComfyUI's temp folder and
    # those must not be touched.
    temp_root = comfy_temp_dir()
    removed = 0
    size = 0
    for subfolder, filename in list(_our_renders):
        path = os.path.join(temp_root, subfolder, filename) if subfolder \
            else os.path.join(temp_root, filename)
        try:
            if os.path.isfile(path):
                size += os.path.getsize(path)
                os.remove(path)
                removed += 1
        except OSError:
            continue
        _our_renders.discard((subfolder, filename))

    if removed:
        log(f"  removed {removed} renders ({size / 1048576:.1f} MB)")
    deleted += removed
    freed += size

    if deleted:
        log(f"cleanup: {deleted} files, {freed / 1048576:.1f} MB freed")
    else:
        log("cleanup: nothing to remove")

    return {"deleted": deleted, "bytes": freed, "skipped": False}


def find_audio_input_node(graph):
    if AUDIO_INPUT_NODE:
        return str(AUDIO_INPUT_NODE)
    for node_id, node in graph.items():
        ct = node.get("class_type", "").lower().replace(" ", "")
        if any(h in ct for h in LOADER_HINTS):
            return node_id
    return None


DIRECTION_HINTS = ("voicedirection", "voice_direction")
INSTRUCTION_KEYS = ("instruction", "direction", "style", "prompt")


def find_direction_node(graph):
    if INSTRUCTION_NODE:
        return str(INSTRUCTION_NODE)
    for node_id, node in graph.items():
        ct = node.get("class_type", "").lower().replace(" ", "")
        if any(h in ct for h in DIRECTION_HINTS):
            return node_id
    return None


def apply_cfg(graph):
    """Override cfg_scale on the Breeze node, if a value is selected.

    Only Breeze nodes expose cfg_scale, so setting every literal one is
    safe and avoids caring which mode the workflow uses. A linked input
    is left alone - that means the user wired something into it.
    """
    value = CFG_CHOICES[_cfg_index]
    if value is None:
        return None

    changed = []
    for node_id, node in graph.items():
        inputs = node.get("inputs", {})
        if "cfg_scale" in inputs and not isinstance(inputs["cfg_scale"], list):
            inputs["cfg_scale"] = value
            changed.append(node_id)
    return value if changed else None


def cycle_cfg():
    global _cfg_index
    _cfg_index = (_cfg_index + 1) % len(CFG_CHOICES)
    value = CFG_CHOICES[_cfg_index]
    log(f"cfg_scale: {'workflow default' if value is None else value}")
    return "workflow" if value is None else str(value)


def apply_instruction(graph, instruction):
    """Write the generated instruction into the Voice Direction node."""
    if INSTRUCTION_NODE is False or not instruction:
        return None

    node_id = find_direction_node(graph)
    if node_id is None or node_id not in graph:
        return None

    inputs = graph[node_id].get("inputs", {})
    for key in INSTRUCTION_KEYS:
        if key in inputs and not isinstance(inputs[key], list):
            inputs[key] = instruction
            return node_id
    return None


def find_reference_node(graph, speech_node):
    """The audio loader that isn't the speech input - i.e. the voice being cloned."""
    if REFERENCE_NODE:
        return str(REFERENCE_NODE)
    for node_id, node in graph.items():
        if str(node_id) == str(speech_node):
            continue
        ct = node.get("class_type", "").lower().replace(" ", "")
        if any(h in ct for h in LOADER_HINTS):
            return node_id
    return None


def ensure_voice_available(name):
    """Copy a clip from the voices folder into ComfyUI's input folder.

    `name` may include a subfolder, e.g. "male/gruff.mp3". ComfyUI's
    input folder stays flat, so the separator is folded into the
    filename: "tts_voice_male__gruff.mp3".

    Returns the filename ComfyUI should load, or None if it's missing.
    Skips the copy when an identical file is already there.
    """
    relative = str(name).replace("\\", "/").strip("/")
    source = os.path.join(VOICES_DIR, *relative.split("/"))

    if not os.path.isfile(source):
        # Might already be a file sitting directly in ComfyUI's input.
        if os.path.isfile(os.path.join(COMFY_INPUT_DIR, relative)):
            return relative
        log(f"voice not found: {relative}")
        return None

    target_name = VOICE_PREFIX + relative.replace("/", "__")
    target = os.path.join(COMFY_INPUT_DIR, target_name)

    try:
        src_stat = os.stat(source)
        if os.path.isfile(target):
            dst_stat = os.stat(target)
            same = (src_stat.st_size == dst_stat.st_size
                    and int(src_stat.st_mtime) <= int(dst_stat.st_mtime))
            if same:
                return target_name

        os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
        shutil.copy2(source, target)
        log(f"voice ready: {relative}")
        return target_name
    except OSError as exc:
        log(f"could not copy voice: {exc}")
        return None


def current_voice():
    """Reference clip filename from voice.txt, or None to leave it alone."""
    try:
        with open(VOICE_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        return name or None
    except OSError:
        return None


def set_loader_file(graph, node_id, filename):
    inputs = graph[node_id]["inputs"]
    for key in ("audio", "audio_file", "file", "path"):
        if key in inputs and not isinstance(inputs[key], list):
            inputs[key] = filename
            return True
    inputs["audio"] = filename
    return True


def prepare_graph(recording_name, instruction=None):
    with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
        graph = json.load(f)

    if "prompt" in graph and "nodes" not in graph:
        graph = graph["prompt"]

    graph = copy.deepcopy(graph)

    node_id = find_audio_input_node(graph)
    if node_id is None:
        raise RuntimeError(
            "No LoadAudio node found. Set AUDIO_INPUT_NODE to the node's id."
        )

    if node_id not in graph:
        available = ", ".join(
            i for i, n in graph.items()
            if any(h in n.get("class_type", "").lower().replace(" ", "")
                   for h in LOADER_HINTS)
        )
        raise RuntimeError(
            f"AUDIO_INPUT_NODE is set to '{node_id}' but no such node exists. "
            f"Audio loader nodes in this workflow: {available or 'none'}. "
            "Run list_nodes.py to check."
        )

    set_loader_file(graph, node_id, recording_name)

    voice = current_voice()
    if voice:
        resolved = ensure_voice_available(voice)
        if resolved:
            ref_id = find_reference_node(graph, node_id)
            if ref_id and ref_id in graph:
                set_loader_file(graph, ref_id, resolved)

    # If no voice is selected, the reference node keeps whatever the
    # workflow shipped with - which may not exist on this machine.
    # Catch that here rather than letting ComfyUI fail obscurely.
    ref_id = find_reference_node(graph, node_id)
    if ref_id and ref_id in graph:
        ref_inputs = graph[ref_id].get("inputs", {})
        for key in ("audio", "audio_file", "file", "path"):
            ref_file = ref_inputs.get(key)
            if isinstance(ref_file, str):
                if not os.path.isfile(os.path.join(COMFY_INPUT_DIR, ref_file)):
                    raise RuntimeError(
                        f"no reference voice available - '{ref_file}' is not in "
                        f"ComfyUI's input folder. Put an audio clip in "
                        f"{VOICES_DIR} and pick it in the panel."
                    )
                break

    for node in graph.values():
        if "seed" in node.get("inputs", {}):
            if not isinstance(node["inputs"]["seed"], list):
                node["inputs"]["seed"] = random.randint(0, 2**31 - 1)

    used_cfg = apply_cfg(graph)
    if used_cfg is not None:
        log(f"  cfg_scale {used_cfg}")

    apply_instruction(graph, instruction)

    return graph


def collect_text_outputs(entry):
    """Pull text from Show Text style nodes so the transcript is visible."""
    found = []
    for node_id, out in entry.get("outputs", {}).items():
        for key in ("text", "string", "value"):
            block = out.get(key)
            if not block:
                continue
            items = block if isinstance(block, list) else [block]
            for item in items:
                if isinstance(item, str) and item.strip():
                    found.append((node_id, item.strip()))
                elif isinstance(item, dict):
                    inner = item.get("text") or item.get("value")
                    if isinstance(inner, str) and inner.strip():
                        found.append((node_id, inner.strip()))
    return found


def collect_audio_outputs(entry):
    found = []
    for out in entry.get("outputs", {}).values():
        for item in out.get("audio", []) or []:
            found.append(item)
    return found


def interrupt():
    """Stop whatever ComfyUI is currently running."""
    global _cancelled
    _cancelled = True
    try:
        api("/interrupt", {})
        log("cancelled")
    except Exception as exc:
        log(f"cancel failed: {exc}")


def describe_error(entry):
    """Pull the actual failure out of ComfyUI's history entry."""
    bits = []
    for message in entry.get("status", {}).get("messages", []) or []:
        if not isinstance(message, (list, tuple)) or len(message) < 2:
            continue
        kind, data = message[0], message[1]
        if kind != "execution_error" or not isinstance(data, dict):
            continue
        node = data.get("node_type") or data.get("node_id")
        exc = data.get("exception_message") or data.get("exception_type")
        if node or exc:
            bits.append(f"{node}: {exc}")
    return " | ".join(bits) if bits else "check the ComfyUI console"


def run_workflow(recording_name, instruction=None):
    global _cancelled

    graph = prepare_graph(recording_name, instruction)
    _cancelled = False
    prompt_id = api(
        "/prompt", {"prompt": graph, "client_id": CLIENT_ID}
    )["prompt_id"]
    log(f"queued {prompt_id[:8]}")

    deadline = time.time() + GENERATION_TIMEOUT
    while time.time() < deadline:
        if _cancelled:
            raise Cancelled()
        hist = api(f"/history/{prompt_id}")
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"workflow errored - {describe_error(entry)}")
            audio = collect_audio_outputs(entry)
            if audio:
                for node_id, text in collect_text_outputs(entry):
                    log(f'heard [{node_id}]: "{text}"')
                return audio[-1]
            if status.get("completed"):
                raise RuntimeError("workflow finished with no audio output")
        time.sleep(0.15)

    raise RuntimeError("timed out waiting for generation")


def fetch_output(item):
    params = urllib.parse.urlencode(
        {
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        }
    )
    # Remember it so cleanup can delete exactly our own renders and leave
    # other workflows' temp files alone.
    try:
        _our_renders.add((item.get("subfolder", ""), item["filename"]))
    except Exception:
        pass
    with urllib.request.urlopen(f"{COMFY_URL}/view?{params}", timeout=30) as r:
        return r.read()


# --------------------------------------------------------------- playback

def current_input_setting():
    """mic.txt wins if present, otherwise the INPUT_DEVICE config."""
    try:
        with open(MIC_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        if name:
            return name
    except OSError:
        pass
    return INPUT_DEVICE


def clip_peak_db(raw):
    """Peak level of a rendered clip, for spotting silent renders."""
    try:
        data, _ = sf.read(io.BytesIO(raw), always_2d=True)
        peak = float(np.abs(data).max())
        return 20 * np.log10(peak) if peak > 0 else -99.0
    except Exception:
        return 0.0  # unreadable - assume fine rather than loop forever


def render_with_retry(name, instruction):
    """Render, discarding near-silent results and trying again."""
    attempts = RETRY_ON_SILENCE + 1

    for attempt in range(1, attempts + 1):
        item = run_workflow(name, instruction)
        raw = fetch_output(item)
        peak = clip_peak_db(raw)

        if peak > SILENCE_THRESHOLD_DB:
            return raw

        if attempt < attempts:
            log(f"silent render ({peak:.0f} dBFS) - retrying {attempt}/{attempts - 1}")
        else:
            log(f"still silent after {attempts} attempts - giving up")
            return raw

    return raw


def resolve_input_device(name):
    if name is None:
        return None
    if isinstance(name, int) or str(name).isdigit():
        return int(name)
    needle = str(name).lower()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
            return i
    raise RuntimeError(f"no input device matching '{name}'")


def resolve_device(name):
    if name is None:
        return None
    if isinstance(name, int) or str(name).isdigit():
        return int(name)
    needle = str(name).lower()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0 and needle in dev["name"].lower():
            return i
    raise RuntimeError(f"no output device matching '{name}'")


def resample_to(data, src_sr, dst_sr):
    """Resample audio so it plays at the right speed on the target device.

    VB-Cable runs at a fixed rate (usually 48kHz) while Breeze renders at
    24kHz. Without this, the clip plays back at double speed.
    """
    if src_sr == dst_sr or src_sr <= 0 or dst_sr <= 0:
        return data, src_sr

    try:
        from scipy.signal import resample_poly
        from math import gcd
        factor = gcd(int(src_sr), int(dst_sr))
        up = int(dst_sr) // factor
        down = int(src_sr) // factor
        return resample_poly(data, up, down, axis=0), dst_sr
    except Exception:
        pass

    # Linear interpolation fallback - fine for speech.
    frames = int(round(len(data) * dst_sr / src_sr))
    if frames <= 0:
        return data, src_sr
    src_x = np.arange(len(data))
    dst_x = np.linspace(0, len(data) - 1, frames)
    out = np.empty((frames, data.shape[1]), dtype=np.float64)
    for ch in range(data.shape[1]):
        out[:, ch] = np.interp(dst_x, src_x, data[:, ch])
    return out, dst_sr


def device_samplerate(index):
    try:
        info = sd.query_devices(index if index is not None else sd.default.device[1])
        return int(info.get("default_samplerate") or 0)
    except Exception:
        return 0


def apply_boost(data):
    """Raise playback level for loud games, without clipping.

    Normalises to a target peak, applies extra gain, then soft-limits so
    anything pushed past full scale rounds over instead of clipping hard.
    """
    mode = BOOST_MODES[_boost_index]
    label, extra_db = mode
    if extra_db is None:
        return data, label

    peak = float(np.abs(data).max())
    if peak <= 0:
        return data, label

    # Normalise to -1 dBFS, then add the requested gain on top.
    target = 10 ** (-1.0 / 20)
    gain = (target / peak) * (10 ** (extra_db / 20))
    out = data * gain

    # Soft limit: linear below the knee, tanh above, so loud passages
    # compress rather than square off. The ceiling sits below full scale
    # so nothing ever lands exactly at 0 dBFS.
    knee = 0.85
    ceiling = 0.97
    over = np.abs(out) > knee
    if over.any():
        sign = np.sign(out[over])
        excess = np.abs(out[over]) - knee
        span = ceiling - knee
        out[over] = sign * (knee + span * np.tanh(excess / span))

    return np.clip(out, -ceiling, ceiling), label


def toggle_monitor():
    global _monitor_enabled
    _monitor_enabled = not _monitor_enabled
    log(f"monitor {'ON' if _monitor_enabled else 'OFF'}"
        f"{' - clips also play on your headphones' if _monitor_enabled else ''}")
    return _monitor_enabled


def cycle_boost():
    global _boost_index
    _boost_index = (_boost_index + 1) % len(BOOST_MODES)
    log(f"boost: {BOOST_MODES[_boost_index][0]}")
    return BOOST_MODES[_boost_index][0]


def play_on(device, data, sr):
    """Blocking playback on one specific device."""
    channels = data.shape[1]
    with sd.OutputStream(samplerate=sr, channels=channels,
                         device=device, dtype="float32") as stream:
        stream.write(np.ascontiguousarray(data, dtype=np.float32))


def fit_for_device(data, sr, device):
    """Resample and channel-match a clip for one output device."""
    target_sr = device_samplerate(device)
    if _resample_enabled and target_sr and target_sr != sr:
        data, sr = resample_to(data, sr, target_sr)

    if data.shape[1] == 1:
        try:
            info = sd.query_devices(device if device is not None else sd.default.device[1])
            if info["max_output_channels"] >= 2:
                data = data.repeat(2, axis=1)
        except Exception:
            pass
    return data, sr


def play_bytes(raw):
    global _suspend_passthrough

    source, source_sr = sf.read(io.BytesIO(raw), always_2d=True)
    device = resolve_device(OUTPUT_DEVICE)

    target_sr = device_samplerate(device)
    if not _resample_enabled:
        log(f"resample OFF - sending {source_sr} Hz to a {target_sr} Hz device")
    elif target_sr and target_sr != source_sr:
        log(f"resampled {target_sr} Hz - {len(source)/source_sr:.2f}s clip")
    else:
        log(f"no resample needed - both at {source_sr} Hz")

    # The cable feed is never boosted - what the game hears stays as
    # rendered. Volume settings only affect the local monitor copy.
    cable_data, cable_sr = fit_for_device(source.copy(), source_sr, device)

    monitor = None
    if _monitor_enabled:
        try:
            mon_device = resolve_device(MONITOR_DEVICE) if MONITOR_DEVICE else None
            mon_data, mon_sr = fit_for_device(source.copy(), source_sr, mon_device)
            before = float(np.abs(mon_data).max())
            mon_data, label = apply_boost(mon_data)
            if BOOST_MODES[_boost_index][1] is not None:
                after = float(np.abs(mon_data).max())
                b = 20 * np.log10(before) if before > 0 else -99
                a = 20 * np.log10(after) if after > 0 else -99
                log(f"monitor {label}: {b:.0f} -> {a:.0f} dBFS (local only)")
            monitor = (mon_device, mon_data, mon_sr)
        except Exception as exc:
            log(f"monitor failed: {exc}")

    _suspend_passthrough = True
    try:
        sd.stop()
        with _playback_lock:
            thread = None
            if monitor is not None:
                mon_device, mon_data, mon_sr = monitor

                def run_monitor():
                    try:
                        play_on(mon_device, mon_data, mon_sr)
                    except Exception as exc:
                        log(f"monitor playback failed: {exc}")

                thread = threading.Thread(target=run_monitor, daemon=True)
                thread.start()

            sd.play(cable_data, cable_sr, device=device)
            sd.wait()

            if thread is not None:
                thread.join(timeout=2)
    finally:
        _suspend_passthrough = False


# ---------------------------------------------------------------- actions

def analyse_recording(name):
    """Measure the take and build a delivery instruction from it."""
    if INSTRUCTION_NODE is False:
        return None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import prosody
        path = os.path.join(COMFY_INPUT_DIR, name)
        data, sr = sf.read(path, always_2d=True)
        text = prosody.describe(prosody.analyse(data, sr))
        if INSTRUCTION_SUFFIX:
            text = f"{text}, {INSTRUCTION_SUFFIX}"
        return text
    except Exception as exc:
        log(f"prosody analysis skipped: {exc}")
        return None


def do_render():
    global _rendering, _last_clip, _last_instruction

    name = stop_recording()

    if name is TOO_SHORT:
        return

    if name is None:
        # Not recording - treat this as "give me another take".
        name = _last_recording
        if name is None:
            log("nothing recorded yet - press your record key first")
            return
        log("re-rolling the last take")
    else:
        _last_instruction = analyse_recording(name)
        if _last_instruction:
            log(f"delivery: {_last_instruction}")

    with _lock:
        if _rendering:
            log("already rendering")
            return
        _rendering = True

    play_after = False
    try:
        t0 = time.time()
        _last_clip = render_with_retry(name, _last_instruction)
        if _autoplay:
            log(f"READY in {time.time() - t0:.1f}s - autoplaying")
            play_after = True
        else:
            log(f"READY in {time.time() - t0:.1f}s - press your play key")
    except Cancelled:
        log("render cancelled")
    except Exception as exc:
        log(f"ERROR: {exc}")
    finally:
        with _lock:
            _rendering = False

    # Playback happens after the flag is cleared. Otherwise the render
    # would look "still running" for as long as the clip lasts, and the
    # next re-roll would be refused.
    if play_after:
        do_play()


def do_play():
    if _last_clip is None:
        log("nothing to play yet")
        return
    try:
        log("playing")
        play_bytes(_last_clip)
    except Exception as exc:
        log(f"ERROR: {exc}")


# ------------------------------------------------------------------ server

ROUTES = {
    "/start": lambda: start_recording(),
    "/render": lambda: threading.Thread(target=do_render, daemon=True).start(),
    "/play": lambda: threading.Thread(target=do_play, daemon=True).start(),
    "/cancel": lambda: threading.Thread(target=interrupt, daemon=True).start(),
    "/passthrough": lambda: threading.Thread(target=toggle_passthrough, daemon=True).start(),
    "/passthrough/on": lambda: threading.Thread(target=start_passthrough, daemon=True).start(),
    "/passthrough/off": lambda: threading.Thread(target=stop_passthrough, daemon=True).start(),
    "/resample": lambda: toggle_resample(),
    "/autoplay": lambda: toggle_autoplay(),
    "/boost": lambda: cycle_boost(),
    "/cfg": lambda: cycle_cfg(),
    "/monitor": lambda: toggle_monitor(),
    "/cleanup": lambda: threading.Thread(target=cleanup_generated, daemon=True).start(),
    "/status": lambda: None,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?")[0].rstrip("/") or "/"
        action = ROUTES.get(route)
        if action is None:
            self.send_response(404)
            self.end_headers()
            return
        action()

        if route == "/status":
            body = json.dumps({
                "passthrough": _passthrough,
                "resample": _resample_enabled,
                "autoplay": _autoplay,
                "boost": BOOST_MODES[_boost_index][0],
                "cfg": CFG_CHOICES[_cfg_index],
                "monitor": _monitor_enabled,
                "recording": _recording,
                "rendering": _rendering,
                "has_clip": _last_clip is not None,
            }).encode()
        else:
            body = b"ok"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def probe_inputs():
    """Try to open every input device and report which ones actually work."""
    print("\nProbing input devices. This takes a moment.\n")

    default_in = sd.default.device[0]
    working = []

    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0:
            continue

        api = hostapi_name(i)
        mark = "  (Windows default)" if i == default_in else ""
        print(f"  [{i}] {dev['name']}")
        print(f"       {api}{mark}")

        try:
            stream, rate, chan, _ = open_input_stream(
                [i], lambda *a: None, prefer_rate=RECORD_SAMPLERATE
            )
            stream.stop()
            stream.close()
            print(f"       OPENS OK at {rate} Hz, {chan}ch")
            working.append((i, dev["name"], api, rate, chan))
        except Exception as exc:
            msg = str(exc).split(" - ")[-1][:70]
            print(f"       FAILED: {msg}")
        print()

    if working:
        print("Usable input devices:\n")
        for i, name, api, rate, chan in working:
            print(f"  [{i}] {name}  ({api}, {rate} Hz, {chan}ch)")
        print("\nPick one and set it in the panel, or put its number in mic.txt.\n")
    else:
        print("Nothing opened. Another program may be holding the device,")
        print("or microphone access is blocked in Windows privacy settings.\n")


def main():
    if "--probe" in sys.argv:
        probe_inputs()
        return

    if "--inputs" in sys.argv:
        print("\nInput (recording) devices:\n")
        default_in = sd.default.device[0]
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                mark = "  <- current default" if i == default_in else ""
                print(f"  [{i}] {dev['name']}{mark}")
        print("\nSet INPUT_DEVICE at the top of this file to the number")
        print("or a part of the name, e.g. INPUT_DEVICE = \"MIC\"\n")
        return

    if not os.path.isfile(WORKFLOW_JSON):
        print(f"Workflow not found: {WORKFLOW_JSON}")
        print("Export it from ComfyUI with: Workflow -> Export (API)")
        sys.exit(1)

    try:
        resolve_device(OUTPUT_DEVICE)
    except RuntimeError as exc:
        print(exc)
        print("\nAvailable output devices:")
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                print(f"  [{i}] {dev['name']}")
        sys.exit(1)

    log(f"ready on port {LISTEN_PORT}")
    log("G1 = record   G2 = render   G3 = passthrough   G4 = cancel   G5 = play")
    HTTPServer(("127.0.0.1", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
