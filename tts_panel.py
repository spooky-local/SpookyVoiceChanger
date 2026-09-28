#!/usr/bin/env python3
"""
Control panel for the ComfyUI TTS service.

Pick the cloned voice and your microphone, start and stop the service,
and watch the log - without touching any files.

    python tts_panel.py
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tts_service as cfg  # noqa: E402  (path must be set first)

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".mp4", ".ogg"}

PANEL_VERSION = "2.4"   # bumped whenever this file changes

# ---------------------------------------------------------------- palette

BG = "#1b1c20"          # window
PANEL = "#232429"       # raised areas
FIELD = "#2b2d33"       # inputs
BORDER = "#34363d"
TEXT = "#e2e4ea"
MUTED = "#8b8f9a"
ACCENT = "#5ba7e8"      # light blue
ACCENT_HOVER = "#71b6ee"
ACCENT_DOWN = "#4a93d2"
ACCENT_TEXT = "#0f1116"
STOP = "#c9605f"
STOP_HOVER = "#d6736f"
STOP_DOWN = "#b45250"
OK = "#5fcf8a"
WARN = "#e2b45f"
HEARD = "#c58ff0"       # what Whisper transcribed - stands out from the rest


# ---------------------------------------------------------- rounded button

class RoundButton(tk.Canvas):
    """A flat button with rounded corners. ttk can't do these natively."""

    def __init__(self, parent, text, command=None, width=130, height=34,
                 fill=ACCENT, hover=ACCENT_HOVER, down=ACCENT_DOWN,
                 fg=ACCENT_TEXT, radius=9):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0, bd=0)
        self.command = command
        self._fill = fill
        self._hover = hover
        self._down = down
        self._fg = fg
        self._radius = radius
        self._bw = width
        self._bh = height
        self._text = text
        self._draw(self._fill)

        self.bind("<Enter>", lambda e: self._draw(self._hover))
        self.bind("<Leave>", lambda e: self._draw(self._fill))
        self.bind("<ButtonPress-1>", lambda e: self._draw(self._down))
        self.bind("<ButtonRelease-1>", self._release)

    def _round_points(self, w, h, r):
        return [
            r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h,
            w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0,
        ]

    def _draw(self, colour):
        self.delete("all")
        self.create_polygon(
            self._round_points(self._bw, self._bh, self._radius),
            smooth=True, splinesteps=24, fill=colour, outline=colour,
        )
        self.create_text(
            self._bw / 2, self._bh / 2, text=self._text,
            fill=self._fg, font=("Segoe UI", 10, "bold"),
        )

    def _release(self, _event):
        self._draw(self._hover)
        if self.command:
            self.command()

    def restyle(self, text=None, fill=None, hover=None, down=None):
        if text is not None:
            self._text = text
        if fill is not None:
            self._fill = fill
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self._draw(self._fill)


# ------------------------------------------------------------------ helpers

ROOT_CATEGORY = "(all)"
UNSORTED = "(unsorted)"


def list_categories():
    """Subfolders of the voices folder, e.g. male / female / characters."""
    try:
        os.makedirs(cfg.VOICES_DIR, exist_ok=True)
        subs = sorted(
            (d for d in os.listdir(cfg.VOICES_DIR)
             if os.path.isdir(os.path.join(cfg.VOICES_DIR, d))
             and not d.startswith(".")),
            key=str.lower,
        )
    except OSError:
        return [ROOT_CATEGORY]

    categories = [ROOT_CATEGORY]
    if any_loose_files():
        categories.append(UNSORTED)
    return categories + subs


def any_loose_files():
    """True if there are clips sitting directly in the voices folder."""
    try:
        return any(
            os.path.splitext(f)[1].lower() in AUDIO_EXTS
            for f in os.listdir(cfg.VOICES_DIR)
            if os.path.isfile(os.path.join(cfg.VOICES_DIR, f))
        )
    except OSError:
        return False


def list_voices(category=ROOT_CATEGORY):
    """Reference clips, optionally limited to one subfolder.

    Paths are returned relative to the voices folder, so a clip inside
    a subfolder comes back as "male/gruff.mp3".
    """
    try:
        os.makedirs(cfg.VOICES_DIR, exist_ok=True)
    except OSError:
        return []

    found = []

    def collect(folder, prefix):
        try:
            entries = os.listdir(folder)
        except OSError:
            return
        for entry in entries:
            full = os.path.join(folder, entry)
            if os.path.isfile(full) and os.path.splitext(entry)[1].lower() in AUDIO_EXTS:
                found.append(prefix + entry)

    if category == ROOT_CATEGORY:
        collect(cfg.VOICES_DIR, "")
        try:
            for sub in os.listdir(cfg.VOICES_DIR):
                path = os.path.join(cfg.VOICES_DIR, sub)
                if os.path.isdir(path) and not sub.startswith("."):
                    collect(path, sub + "/")
        except OSError:
            pass
    elif category == UNSORTED:
        collect(cfg.VOICES_DIR, "")
    else:
        collect(os.path.join(cfg.VOICES_DIR, category), category + "/")

    return sorted(found, key=str.lower)


HOSTAPI_PREFERENCE = {
    "mme": 0,
    "windows directsound": 1,
    "windows wasapi": 2,
    "windows wdm-ks": 3,
    "asio": 4,
}


def list_mics():
    """One entry per physical mic, using the most reliable audio API.

    Windows lists the same interface once per audio API, and the WDM-KS
    entries often refuse to open. Group by the name before the bracket
    and keep whichever version is most likely to work.
    """
    try:
        import sounddevice as sd

        best = {}
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] <= 0:
                continue
            try:
                api = sd.query_hostapis(dev["hostapi"])["name"].lower()
            except Exception:
                api = "?"
            rank = HOSTAPI_PREFERENCE.get(api, 9)
            key = dev["name"].split("(")[0].strip().lower()
            if key not in best or rank < best[key][0]:
                best[key] = (rank, dev["name"])

        return [name for _, name in sorted(best.values(), key=lambda v: v[1].lower())]
    except Exception:
        return []


def dark_titlebar(root):
    """Ask Windows for a dark title bar. Silently ignored elsewhere."""
    if os.name != "nt":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        # 20 on current Windows 10/11, 19 on older builds.
        for attribute in (20, 19):
            ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if ok == 0:
                break
    except Exception:
        pass


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_file(path, value):
    with open(path, "w", encoding="utf-8") as f:
        f.write(value)


# -------------------------------------------------------------------- panel

class Panel:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.lines = queue.Queue()

        root.title(f"SpookyVoiceChanger  -  panel {PANEL_VERSION}")
        root.configure(bg=BG)
        root.minsize(1180, 580)
        dark_titlebar(root)

        self._style(root)

        outer = tk.Frame(root, bg=BG, padx=16, pady=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        # Category ----------------------------------------------------------
        tk.Label(outer, text="Category", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=6)

        self.category = ttk.Combobox(outer, state="readonly",
                                     values=list_categories())
        self.category.grid(row=0, column=1, sticky="ew", padx=(12, 8), pady=6)
        self.category.bind("<<ComboboxSelected>>", self.on_category)
        self.category.set(ROOT_CATEGORY)

        RoundButton(outer, "Refresh", self.refresh, width=86, height=30,
                    fill=FIELD, hover="#35373f", down="#202126",
                    fg=TEXT).grid(row=0, column=2, pady=6)

        RoundButton(outer, "Clean up", self.on_cleanup, width=86, height=30,
                    fill=FIELD, hover="#35373f", down="#202126",
                    fg=TEXT).grid(row=1, column=2, pady=6)

        # Voice ------------------------------------------------------------
        tk.Label(outer, text="Cloned voice", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=6)

        self.voice = ttk.Combobox(outer, state="readonly", values=list_voices())
        self.voice.grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=6)
        self.voice.bind("<<ComboboxSelected>>", self.on_voice)

        # Mic --------------------------------------------------------------
        tk.Label(outer, text="Microphone", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=6)

        self.mic = ttk.Combobox(outer, state="readonly", values=list_mics())
        self.mic.grid(row=2, column=1, sticky="ew", padx=(12, 8), pady=6)
        self.mic.bind("<<ComboboxSelected>>", self.on_mic)

        # Controls ---------------------------------------------------------
        bar = tk.Frame(outer, bg=BG)
        bar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(16, 10))

        self.toggle = RoundButton(bar, "Start service", self.on_toggle, width=140)
        self.toggle.pack(side="left")

        self.status = tk.Label(bar, text="stopped", bg=BG, fg=MUTED,
                               font=("Segoe UI", 9))
        self.status.pack(side="left", padx=14)

        self.passthrough_on = False
        self.passthrough = RoundButton(
            bar, "Mic passthrough: OFF", self.on_passthrough, width=190,
            fill=FIELD, hover="#35373f", down="#202126", fg=TEXT,
        )
        self.passthrough.pack(side="left", padx=(0, 8))

        self.resample_on = True
        self.resample = RoundButton(
            bar, "Resample: ON", self.on_resample, width=132,
            fill=OK, hover="#74dc9c", down="#4fb87a", fg=ACCENT_TEXT,
        )
        self.resample.pack(side="left", padx=(0, 8))

        self.autoplay_on = False
        self.autoplay = RoundButton(
            bar, "Autoplay: OFF", self.on_autoplay, width=132,
            fill=FIELD, hover="#35373f", down="#202126", fg=TEXT,
        )
        self.autoplay.pack(side="left", padx=(0, 8))

        self.boost_modes = ["OFF", "Normalize", "Boost +6", "Boost +12"]
        self.boost_index = 0
        self.boost = RoundButton(
            bar, "Volume: OFF", self.on_boost, width=140,
            fill=FIELD, hover="#35373f", down="#202126", fg=TEXT,
        )
        self.boost.pack(side="left", padx=(0, 8))

        self.monitor_on = False
        self.monitor = RoundButton(
            bar, "Monitor: OFF", self.on_monitor, width=132,
            fill=FIELD, hover="#35373f", down="#202126", fg=TEXT,
        )
        self.monitor.pack(side="left", padx=(0, 8))

        self.cfg_labels = ["workflow", "1.0", "2.0", "3.0", "4.0"]
        self.cfg_index = 0
        self.cfg = RoundButton(
            bar, "CFG: workflow", self.on_cfg, width=140,
            fill=FIELD, hover="#35373f", down="#202126", fg=TEXT,
        )
        self.cfg.pack(side="left", padx=(0, 8))

        RoundButton(bar, "Clear log", self.clear, width=96,
                    fill=FIELD, hover="#35373f", down="#202126",
                    fg=TEXT).pack(side="right")

        # Actions ------------------------------------------------------------
        # The same four things the macro keys do, for anyone who hasn't set
        # keys up - or just wants to test each step.
        actions = tk.Frame(outer, bg=BG)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        tk.Label(actions, text="Actions", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))

        self.btn_record = RoundButton(
            actions, "Record", lambda: self.action("/start", "record"),
            width=110, fill=ACCENT, hover=ACCENT_HOVER, down=ACCENT_DOWN,
        )
        self.btn_record.pack(side="left", padx=(0, 8))

        self.btn_generate = RoundButton(
            actions, "Generate", lambda: self.action("/render", "generate"),
            width=118, fill=ACCENT, hover=ACCENT_HOVER, down=ACCENT_DOWN,
        )
        self.btn_generate.pack(side="left", padx=(0, 8))

        self.btn_play = RoundButton(
            actions, "Play", lambda: self.action("/play", "play"),
            width=100, fill=OK, hover="#74dc9c", down="#4fb87a",
        )
        self.btn_play.pack(side="left", padx=(0, 8))

        self.btn_cancel = RoundButton(
            actions, "Cancel", lambda: self.action("/cancel", "cancel"),
            width=100, fill=STOP, hover=STOP_HOVER, down=STOP_DOWN,
            fg="#1b1c20",
        )
        self.btn_cancel.pack(side="left", padx=(0, 8))

        # Log --------------------------------------------------------------
        outer.rowconfigure(5, weight=1)
        wrap = tk.Frame(outer, bg=BORDER, highlightthickness=1,
                        highlightbackground=BORDER, bd=0)
        wrap.grid(row=5, column=0, columnspan=3, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.log = tk.Text(wrap, height=15, wrap="word", state="disabled",
                           bg=PANEL, fg=TEXT, insertbackground=TEXT,
                           font=("Consolas", 9), relief="flat",
                           padx=10, pady=8, selectbackground=ACCENT_DOWN,
                           highlightthickness=0, bd=0)
        self.log.grid(row=0, column=0, sticky="nsew")
        self.log.tag_configure("ok", foreground=OK)
        self.log.tag_configure("warn", foreground=WARN)
        self.log.tag_configure("err", foreground=STOP)
        self.log.tag_configure("dim", foreground=MUTED)
        self.log.tag_configure("heard", foreground=HEARD,
                               font=("Consolas", 9, "bold"))

        scroll = ttk.Scrollbar(wrap, command=self.log.yview,
                               style="Dark.Vertical.TScrollbar")
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        self.load_current()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.drain)

    # ---------------------------------------------------------------- theme

    def _style(self, root):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "TCombobox",
            fieldbackground=FIELD, background=FIELD, foreground=TEXT,
            arrowcolor=ACCENT, bordercolor=BORDER, lightcolor=FIELD,
            darkcolor=FIELD, selectbackground=FIELD, selectforeground=TEXT,
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            background=[("readonly", FIELD)],
            foreground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT)],
            arrowcolor=[("active", ACCENT_HOVER)],
        )

        # The dropdown list is a plain tk widget and needs theming separately.
        root.option_add("*TCombobox*Listbox.background", FIELD)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)
        root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 9")

        style.configure(
            "Dark.Vertical.TScrollbar",
            background=FIELD, troughcolor=PANEL, bordercolor=PANEL,
            arrowcolor=MUTED, lightcolor=FIELD, darkcolor=FIELD,
        )
        style.map("Dark.Vertical.TScrollbar",
                  background=[("active", "#3a3d45")])

    # ---------------------------------------------------------------- state

    def load_current(self):
        voice = read_file(cfg.VOICE_FILE)

        # Jump to the category the saved voice lives in.
        if voice and "/" in voice:
            folder = voice.split("/")[0]
            if folder in self.category["values"]:
                self.category.set(folder)
                self.voice["values"] = list_voices(folder)

        values = self.voice["values"]
        if voice and voice in values:
            self.voice.set(voice)
        elif values:
            self.voice.set(values[0])
            write_file(cfg.VOICE_FILE, self.voice.get())
        else:
            self.write(f" no clips in {cfg.VOICES_DIR}\n", "warn")
            self.write(" drop reference audio there, then press Refresh\n", "dim")
            self.write(" subfolders become categories, e.g. voices\\male\n", "dim")

        mic = read_file(cfg.MIC_FILE)
        if mic:
            for name in self.mic["values"]:
                if mic.lower() in name.lower():
                    self.mic.set(name)
                    break

    def on_category(self, _=None):
        category = self.category.get()
        clips = list_voices(category)
        self.voice["values"] = clips
        if clips:
            self.voice.set(clips[0])
            write_file(cfg.VOICE_FILE, clips[0])
            self.write(f" category {category} -> {clips[0]}\n", "ok")
        else:
            self.voice.set("")
            self.write(f" no clips in {category}\n", "warn")

    def refresh(self):
        self.category["values"] = list_categories()
        if self.category.get() not in self.category["values"]:
            self.category.set(ROOT_CATEGORY)
        self.voice["values"] = list_voices(self.category.get())
        self.mic["values"] = list_mics()
        self.write(" refreshed voices and devices\n", "dim")

    def on_voice(self, _=None):
        write_file(cfg.VOICE_FILE, self.voice.get())
        self.write(f" voice -> {self.voice.get()}\n", "ok")

    def on_mic(self, _=None):
        write_file(cfg.MIC_FILE, self.mic.get())
        self.write(f" mic -> {self.mic.get()}\n", "ok")

    # -------------------------------------------------------------- service

    def ping(self, path):
        """Fire an action at the running service."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{cfg.LISTEN_PORT}{path}", timeout=3
            ) as r:
                return r.read()
        except Exception as exc:
            self.write(f" service not responding: {exc}\n", "err")
            return None

    def on_passthrough(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/passthrough") is None:
            return

        self.passthrough_on = not self.passthrough_on
        if self.passthrough_on:
            self.passthrough.restyle(
                text="Mic passthrough: ON", fill=OK,
                hover="#74dc9c", down="#4fb87a",
            )
            self.passthrough._fg = ACCENT_TEXT
        else:
            self.passthrough.restyle(
                text="Mic passthrough: OFF", fill=FIELD,
                hover="#35373f", down="#202126",
            )
            self.passthrough._fg = TEXT
        self.passthrough._draw(self.passthrough._fill)

    def on_resample(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/resample") is None:
            return

        self.resample_on = not self.resample_on
        if self.resample_on:
            self.resample._fg = ACCENT_TEXT
            self.resample.restyle(text="Resample: ON", fill=OK,
                                  hover="#74dc9c", down="#4fb87a")
        else:
            self.resample._fg = TEXT
            self.resample.restyle(text="Resample: OFF", fill=FIELD,
                                  hover="#35373f", down="#202126")

    def on_autoplay(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/autoplay") is None:
            return

        self.autoplay_on = not self.autoplay_on
        if self.autoplay_on:
            self.autoplay._fg = ACCENT_TEXT
            self.autoplay.restyle(text="Autoplay: ON", fill=OK,
                                  hover="#74dc9c", down="#4fb87a")
        else:
            self.autoplay._fg = TEXT
            self.autoplay.restyle(text="Autoplay: OFF", fill=FIELD,
                                  hover="#35373f", down="#202126")

    def on_boost(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/boost") is None:
            return

        self.boost_index = (self.boost_index + 1) % len(self.boost_modes)
        label = self.boost_modes[self.boost_index]

        if self.boost_index == 0:
            self.boost._fg = TEXT
            self.boost.restyle(text="Volume: OFF", fill=FIELD,
                               hover="#35373f", down="#202126")
        else:
            self.boost._fg = ACCENT_TEXT
            self.boost.restyle(text=f"Volume: {label}", fill=OK,
                               hover="#74dc9c", down="#4fb87a")

    def on_monitor(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/monitor") is None:
            return

        self.monitor_on = not self.monitor_on
        if self.monitor_on:
            self.monitor._fg = ACCENT_TEXT
            self.monitor.restyle(text="Monitor: ON", fill=OK,
                                 hover="#74dc9c", down="#4fb87a")
        else:
            self.monitor._fg = TEXT
            self.monitor.restyle(text="Monitor: OFF", fill=FIELD,
                                 hover="#35373f", down="#202126")

    def on_cfg(self):
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return

        if self.ping("/cfg") is None:
            return

        self.cfg_index = (self.cfg_index + 1) % len(self.cfg_labels)
        label = self.cfg_labels[self.cfg_index]

        if self.cfg_index == 0:
            self.cfg._fg = TEXT
            self.cfg.restyle(text="CFG: workflow", fill=FIELD,
                             hover="#35373f", down="#202126")
        else:
            self.cfg._fg = ACCENT_TEXT
            self.cfg.restyle(text=f"CFG: {label}", fill=ACCENT,
                             hover=ACCENT_HOVER, down=ACCENT_DOWN)

    def on_cleanup(self):
        """Delete recordings, voice copies and renders this tool generated."""
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return
        self.ping("/cleanup")

    def action(self, path, label):
        """Fire one of the record/generate/play/cancel actions."""
        if not (self.proc and self.proc.poll() is None):
            self.write(" start the service first\n", "warn")
            return
        self.ping(path)

    def on_toggle(self):
        if self.proc and self.proc.poll() is None:
            self.stop()
        else:
            self.start()

    def start(self):
        script = os.path.join(HERE, "tts_service.py")
        if not os.path.isfile(script):
            self.write(" tts_service.py not found next to this panel\n", "err")
            return

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", script],
                cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=flags,
            )
        except Exception as exc:
            self.write(f" could not start: {exc}\n", "err")
            return

        threading.Thread(target=self.pump, daemon=True).start()
        self.toggle.restyle(text="Stop service", fill=STOP,
                            hover=STOP_HOVER, down=STOP_DOWN)
        self.status.config(text="running", fg=OK)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.set_stopped()
        self.write(" service stopped\n", "dim")

    def set_stopped(self):
        self.toggle.restyle(text="Start service", fill=ACCENT,
                            hover=ACCENT_HOVER, down=ACCENT_DOWN)
        self.status.config(text="stopped", fg=MUTED)
        self.passthrough_on = False
        self.passthrough._fg = TEXT
        self.passthrough.restyle(text="Mic passthrough: OFF", fill=FIELD,
                                 hover="#35373f", down="#202126")
        self.autoplay_on = False
        self.autoplay._fg = TEXT
        self.autoplay.restyle(text="Autoplay: OFF", fill=FIELD,
                              hover="#35373f", down="#202126")
        self.boost_index = 0
        self.boost._fg = TEXT
        self.boost.restyle(text="Volume: OFF", fill=FIELD,
                           hover="#35373f", down="#202126")
        self.monitor_on = False
        self.monitor._fg = TEXT
        self.monitor.restyle(text="Monitor: OFF", fill=FIELD,
                             hover="#35373f", down="#202126")
        self.cfg_index = 0
        self.cfg._fg = TEXT
        self.cfg.restyle(text="CFG: workflow", fill=FIELD,
                         hover="#35373f", down="#202126")

    def pump(self):
        proc = self.proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.lines.put(line)
        self.lines.put(" service exited\n")

    # ------------------------------------------------------------------ log

    def drain(self):
        try:
            while True:
                self.write(self.lines.get_nowait())
        except queue.Empty:
            pass

        if self.proc and self.proc.poll() is not None:
            self.proc = None
            self.set_stopped()

        self.root.after(100, self.drain)

    def write(self, text, tag=None):
        if tag is None:
            low = text.lower()
            if "error" in low or "failed" in low:
                tag = "err"
            elif "silent" in low or "retry" in low or "warning" in low:
                tag = "warn"
            elif "heard [" in low:
                tag = "heard"
            elif "ready in" in low or "recording" in low or "voice ready" in low:
                tag = "ok"

        self.log.config(state="normal")
        self.log.insert("end", text, tag or ())
        self.log.see("end")
        self.log.config(state="disabled")

    def clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    Panel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
