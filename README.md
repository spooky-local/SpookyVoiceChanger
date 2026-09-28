# SpookyVoiceChanger — Installation Guide

Speak into your mic, have it come out as a **different voice**, straight into any game's voice chat.

Powered by **Breeze TTS 2** running on a **ComfyUI** backend.

Press one key to record, another to generate, another to play. Roughly **3 seconds** from finishing your sentence to hearing it.

---

## What it actually does

1. You press a key and talk, then press another to stop
2. Whisper transcribes what you said
3. **Breeze TTS 2** speaks those words in a cloned voice of your choosing
4. The audio plays into a virtual microphone that games see as a real one

The voice cloning needs only a short reference clip — **10–20 seconds** of someone talking.

---

## Why it doesn't sound like RVC

Most voice changers use **voice conversion** — they take your actual waveform and reshape it toward a target voice in real time. That's where the thin, metallic, slightly underwater quality comes from. The model is fighting your voice rather than replacing it, and at low latency it has very little to work with.

**This works differently.** Your speech is transcribed to text, and the voice is then **generated from scratch** by a text-to-speech model. There's no conversion step, so there are no conversion artifacts. The output is simply a voice speaking — it has never touched your waveform.

**The trade-offs, so you know what you're choosing:**

| | Voice conversion (RVC and similar) | SpookyVoiceChanger |
|---|---|---|
| **Sound quality** | Often thin and metallic | Clean generated speech |
| **Latency** | Near real-time | ~3 seconds after you stop talking |
| **Your delivery** | Your intonation carries through | Regenerated, so your exact delivery doesn't |
| **Do-overs** | What comes out is what you get | Re-roll until you're happy, then play it |

**It's turn-based rather than live.** You talk, it renders, you play it. That's the price of the quality — but it also means you hear every line before anyone else does, which live voice changers can't offer.

---

## Will it run on my PC?

**The short version:** if you have an NVIDIA graphics card with **8GB of VRAM or more**, yes. With **16GB or more**, it'll feel fast.

### How to check your VRAM

Press **Ctrl+Shift+Esc** to open Task Manager, click **Performance**, then click your **GPU** in the left column. Look for **Dedicated GPU memory** — the number after the slash is your total VRAM.

Or press **Win+R**, type `dxdiag`, press Enter, and check the **Display** tab.

---

### Minimum — it works, but you'll wait

| What | Spec |
|---|---|
| **Graphics card** | NVIDIA with 8GB VRAM (RTX 2070, 3060, 4060...) |
| **RAM** | 16GB |
| **Free disk space** | 10GB |
| **Processor** | Anything from the last 5 years |
| **Operating system** | Windows 10 or 11 |

**Expect roughly 5–8 seconds** per clip. Usable, but you'll notice the pause in conversation.

**At 8GB you'll need these settings** (all explained later in the guide):

- Use the **INT8** model instead of bf16 — it's smaller
- Set **`decode_mode`** to `eager`, not `cuda_graphs`
- Set **`attention`** to `sdpa`
- Use a smaller Whisper model — **`small`** or **`distil-large-v3`**

> The full-quality model file alone is about 6.5GB. On an 8GB card that leaves almost nothing for the speed optimisations, which is why they get turned off.

---

### Recommended — this is where it feels good

| What | Spec |
|---|---|
| **Graphics card** | NVIDIA with **16GB VRAM** (RTX 4070 Ti Super, 4080, 5070 Ti, 3090...) |
| **RAM** | 32GB |
| **Free disk space** | 20GB on an SSD |
| **Operating system** | Windows 10 or 11 |

**Expect about 2 seconds** per clip. Fast enough that conversation flows naturally.

**16GB is the real dividing line.** The fast rendering path needs around 14.4GB of VRAM to work. Below that it falls back to a slower method, and that single difference is most of the gap between 6 seconds and 2 seconds.

---

### Does more than 16GB help?

**Not really.** A 24GB or 32GB card runs it at the same speed as a 16GB one — once the fast path fits, extra VRAM sits unused. Spend the money elsewhere.

**What does help:** a faster GPU generation. A 4090 or 5090 will beat a 3090 even though both have 24GB.

---

### AMD or Intel graphics?

**Not supported.** The Breeze nodes need CUDA, which is NVIDIA-only.

### Can I use my laptop?

**If it has a dedicated NVIDIA GPU with 8GB+, yes.** Laptop cards run slower than their desktop equivalents with the same name, so expect times closer to the minimum-spec figures. Integrated graphics won't work.

---

## Everything else you need

| Requirement | Notes |
|---|---|
| **ComfyUI** | The portable build is easiest |
| **Python 3.10 or newer** | Separate from the one inside ComfyUI |
| **VB-Audio Virtual Cable** | Free. Step 1 covers installing it. |
| **A way to bind keys** | See below |

**For the keys**, any of these work:

- **A gaming keyboard or mouse** with macro keys — Logitech G-series, Razer, Corsair, SteelSeries
- **AutoHotkey** (free) if your hardware has no macro software
- **Nothing at all** — you can drive it entirely from the control panel window, it's just less convenient mid-game

---

## Step 1 — Install VB-Audio Virtual Cable

This is the pipe that carries generated audio into your games.

1. Download it from **vb-audio.com/Cable**
2. **Extract the zip first**, then right-click `VBCABLE_Setup_x64.exe` → **Run as administrator**
3. Click *Install Driver*
4. **Reboot.** It won't work properly until you do.

After rebooting you should have two new audio devices: **CABLE Input** (an output) and **CABLE Output** (an input). That naming is confusing but correct — think of it as a cable with two ends.

---

## Step 2 — Install the Breeze TTS 2 nodes

In ComfyUI Manager, search for **Breeze TTS 2**. Or manually:

```
cd ComfyUI\custom_nodes
git clone https://github.com/Saganaki22/ComfyUI-Breeze-TTS-2.git
```

Restart ComfyUI.

**Set `download_if_missing` to `true`** on the *Breeze TTS 2 Load Model* node for your first run. The model is about 6.5GB and downloads automatically.

> **Important:** on the Load Model node, set **`attention` to `sdpa`**, not `auto`. Auto tries to use FlashAttention 2, which isn't installed in ComfyUI's portable Python, and you'll get `TypeError: 'NoneType' object is not callable`.
>
> **If you have SageAttention installed, use `sageattention` instead** — it's faster than `sdpa`. If you don't know whether you have it, stick with `sdpa`; it always works.

### Settings by VRAM

These are all on the **Breeze TTS 2 Load Model** node.

**If you have 16GB VRAM or more:**

| Setting | Value |
|---|---|
| `model` | **bf16 (best quality)** |
| `decode_mode` | **cuda_graphs** |
| `attention` | `sageattention`, or `sdpa` |
| `dtype` | `auto` |

**If you have 8–12GB VRAM:**

| Setting | Value |
|---|---|
| `model` | **an INT8 build** — smaller, fits alongside everything else |
| `decode_mode` | **eager** |
| `attention` | `sdpa` |
| `dtype` | `auto` |

> **Why turn `cuda_graphs` off on a small card?** It's the setting that makes rendering fast, but it needs roughly 14.4GB of VRAM to work. On an 8GB card there isn't room, and forcing it just causes errors. `eager` is slower but always works.

> **Don't use INT8 on a big card.** It's there to save memory, not time — on a 16GB+ card it's actually *slower* than bf16 as well as lower quality.

---

## Step 3 — Load the included workflow

The workflow is already built for you. Drag **`workflow.json`** into the ComfyUI window, or use **Workflow → Open**.

It looks like this:

```
Load Audio  (your speech)  ─→ Whisper Transcribe ─┐
                                                  ├─→ Breeze Voice Clone ─→ Preview Audio
Load Audio  (voice to clone) ─→ Whisper Transcribe ┘         ▲
                             └───────────────────────────────┘
                                        (reference_audio)
```

**Two separate Load Audio nodes.** One holds the speech to be spoken, the other holds the voice being imitated. Breeze needs both the reference audio *and* a transcript of it, which is why there are two Whisper nodes.

**Before you run it, check one setting** on the *Breeze TTS 2 Load Model* node: `attention` must be **`sdpa`** or **`sageattention`**, never `auto`. See step 2.

### Whisper settings

The two Whisper nodes do different jobs, so they don't get the same settings.

| Node | `task` | Why |
|---|---|---|
| **Reference side** (fed by the voice you're cloning) | **`transcribe`** | Breeze needs the literal words of the reference clip. This one must not translate. |
| **Speech side** (fed by your recording) | **`translate`** in the supplied workflow | See below — either setting works. |

**On `transcribe` vs `translate` for your own speech:**

- **`transcribe`** writes down what you said, in whatever language you said it.
- **`translate`** outputs English no matter what language you spoke.

**If you speak English, they behave almost identically** — translating English to English is close to a passthrough. The supplied workflow uses `translate` and works fine.

**Switch the speech side to `transcribe` if** you want to generate speech in a language other than English. With `translate` you'd say something in Spanish and hear it come back in English.

> If you change this, re-export the workflow: **Workflow → Export (API)**.

**Which Whisper model:**

- **16GB+ VRAM** — `whisper-large-v3-turbo`. Adds roughly a quarter of a second per clip.
- **8–12GB VRAM** — `small` or `distil-large-v3`. Noticeably lighter, and for short conversational lines the accuracy difference is minimal.

> Whisper is not the slow part. Voice Clone takes around 2 seconds; Whisper takes a fraction of that. Only drop to a smaller model if you're tight on VRAM.

### Voice Clone settings

These are already set in the supplied workflow. You don't need to change anything — this is here so you know what they do.

| Setting | Supplied value | What it does |
|---|---|---|
| `cfg_scale` | **1.0** | How closely the output copies the reference voice. **1.0 copies it as-is.** Higher values push away from it, which flattens emotional swings and reads more neutral. The panel's **CFG** button changes this without editing the workflow. |
| `max_new_tokens` | **248** | A hard ceiling on how long one clip can be. See below. |
| `control after generate` | **randomize** | Gives a different take each time you re-roll. Leave it on. |

### About `max_new_tokens`

Breeze generates audio in small chunks called tokens, roughly **12 per second** of speech. This setting caps how many it's allowed to produce before it stops.

**248 tokens is about 20 seconds of audio.** Plenty for conversational lines, which are usually under 5.

**Why not leave it at the 1500 default?** Breeze occasionally gets stuck — it never emits a stop signal and keeps generating until it hits the ceiling. At 1500 that's **around two minutes of silence** you have to sit through. At 248 the worst case is roughly 20 seconds.

**Raise it if your lines get cut off mid-sentence.** Try 500 for longer speeches. The only cost is a longer wait when a stall happens.

> The tool also detects silent renders and automatically retries them, so most stalls never reach you. The lower ceiling just limits the damage when one does.

**Test it manually.** Load any two audio files into the Load Audio nodes and hit Queue. Get this working before going further — the automation can only run a workflow that already works.

> **If you rebuild or restructure the workflow**, you must re-export it: **Workflow → Export (API)**, save as `workflow_api.json`, and re-check `AUDIO_INPUT_NODE` in step 5. Export (API) is *not* the same as Save — the API format is what the script sends to ComfyUI. You don't need to do any of this if you use the workflow as supplied.

---

## Step 4 — Set up the project folder

Put all the project files in one folder. Anywhere you like — `C:\Users\<you>\Desktop\TTS` works.

You should have:

```
TTS\
├── tts_service.py        the engine
├── tts_panel.py          the control panel
├── prosody.py            measures how you said it
├── list_nodes.py         diagnostic helper
├── TTS_Panel.vbs         opens the control panel
├── tts_start.vbs         key trigger — record
├── tts_render.vbs        key trigger — generate
├── tts_play.vbs          key trigger — play
├── tts_cancel.vbs        key trigger — cancel
├── tts_passthrough.vbs   key trigger — mic passthrough
├── tts_hold_start.vbs    optional hold-to-talk, on press
├── tts_hold_end.vbs      optional hold-to-talk, on release
├── workflow.json         open this one in ComfyUI
├── workflow_api.json     the version the script reads
├── INSTALL.md            this guide
└── voices\               put your reference clips here

Two more files appear on their own once you start using it — `mic.txt`
and `voice.txt`, which remember your microphone and voice choice. Leave
them alone; the panel writes them for you.
```

### Install the Python packages

The scripts need three small add-ons for Python. You install them from a command prompt opened **inside your TTS folder**.

**Opening a command prompt in the right place:**

1. Open your **TTS folder** in File Explorer
2. Click once in the **address bar** at the top — the bit showing the folder path
3. Type `cmd` over it and press **Enter**

A black window opens, already pointed at your TTS folder.

**Then type this and press Enter:**

```
pip install sounddevice soundfile numpy
```

Wait for it to finish. You'll see a lot of text scroll past, ending with something like `Successfully installed ...`.

> **"pip is not recognized"?** Python isn't on your system PATH. Easiest fix is to reinstall Python from python.org and **tick "Add python.exe to PATH"** on the first screen of the installer.

> **"Requirement already satisfied"?** That's fine — it means you already have them. Move on.

**What each one does**, in case you're curious: `sounddevice` talks to your microphone and speakers, `soundfile` reads and writes audio files, and `numpy` does the maths on the audio itself.

---

## Step 5 — Configure

**Open `tts_service.py` in a text editor.** Right-click it → **Open with** → **Notepad**. Only one thing needs changing.

> Don't double-click it — that runs the script instead of opening it.

**`COMFY_INPUT_DIR`** — point it at your ComfyUI `input` folder:

```python
COMFY_INPUT_DIR = r"C:\path\to\ComfyUI\input"
```

**`AUDIO_INPUT_NODE`** — **already set correctly for the included workflow.** Leave it alone unless you rebuild the workflow yourself.

If you do rebuild it, find the right node by opening a command prompt in your TTS folder (address bar → type `cmd` → Enter, same as before) and running:

```
python list_nodes.py
```

It prints each Load Audio node with an ID and what it feeds into. **Pick the one that feeds only a Whisper node** — the other one feeds Whisper *and* Voice Clone, and that's your reference voice.

```python
AUDIO_INPUT_NODE = "41"     # use your own number
```

> Getting this backwards is the most common setup mistake. The symptom is unmistakable: every render comes out as a different random voice, because the script has overwritten your reference clip with your own recording.

---

## Step 6 — Add a voice

Drop an audio clip into the `voices\` folder. **10–20 seconds** of clear speech, no music, no background noise.

**Clip quality matters more than anything else.** The model reproduces whatever it's given — hiss, room tone and compression artifacts all get cloned along with the voice. A clean source beats a long one.

Avoid clips ripped from YouTube if you can. If a render sounds thin or hissy, the reference is almost always why.

---

## Step 7 — First run

Start **ComfyUI**, then double-click **`TTS_Panel.vbs`**.

### About that ComfyUI window

When you start ComfyUI you get **two** things: a **black console window**, and a **browser tab** with the node graph in it.

| Window | Can you close it? |
|---|---|
| **Browser tab** with the nodes | **Yes.** Close it freely — SpookyVoiceChanger talks to ComfyUI directly and doesn't need the graph on screen. |
| **Black console window** | **No.** That window *is* ComfyUI. Close it and ComfyUI shuts down, and nothing will render. |

**Minimise the black window, don't close it.** If renders suddenly stop working, check it's still running.

> The browser tab is only an interface. Handy when you want to change workflow settings, but not needed day to day.

### The first time you open it

Windows flags files that came from the internet, so you'll probably see one or both of these.

**"Open File - Security Warning"** — a box asking whether you really want to run it.

- **Untick "Always ask before opening this file"**, then click **Open**
- It won't ask again for that file

**"Windows protected your PC"** (a blue full-screen box) — click **More info**, then **Run anyway**.

### If it refuses with "Access is denied"

Windows has the file blocked rather than just flagged. Fix it once per file:

1. Right-click the file → **Properties**
2. At the bottom of the **General** tab, tick **Unblock**
3. Click **Apply**

**Do this for all the `.vbs` files**, not just the panel. You'll need the others working in Step 8.

> This comes back every time you re-download a file. If a script suddenly stops working after an update, check Unblock first.

### Then, in the panel:

1. Pick your **voice** from the dropdown
2. Pick your **microphone**
3. Click **Start service**

**Test it with the Actions buttons.** Click **Record**, talk for a few seconds, click **Generate**, then click **Play**. Watch the log — you should see the recording captured, the transcript, and the render time.

> **The first render is much slower — this is normal.** ComfyUI has to load the voice model and Whisper into your graphics card's memory, which takes anywhere from ten seconds to a minute depending on your hardware and whether the files are on an SSD.
>
> **Every render after that is fast**, because the models stay loaded. You'll only wait again if you restart ComfyUI.

If that works, everything is set up correctly.

<details>
<summary>Alternative: test via browser URLs</summary>

Some people prefer checking the service directly. With it running, visit these one at a time:

| Visit | Should show |
|---|---|
| `http://127.0.0.1:8765/start` | `RECORDING` |
| *(talk for a few seconds)* | |
| `http://127.0.0.1:8765/render` | `captured 3.2s` then `READY in 2.3s` |
| `http://127.0.0.1:8765/play` | `playing` |

</details>

**If that works, you're done.** If it doesn't, the log in the panel tells you what went wrong.

---

## Step 8 — Bind your keys (optional)

**You can skip this entirely.** The control panel has **Record**, **Generate**, **Play** and **Cancel** buttons that do exactly the same things, so the tool works fully without binding anything.

Keys are worth setting up if you'll use it mid-game, since alt-tabbing to the panel every time gets old fast. If you're just trying it out, skip to Step 9 and come back later.

Each key launches a small script.

### What the `.vbs` files are

The `tts_*.vbs` files in your TTS folder are **three-line text files**. Each one sends a single message to the service that's already running — "start recording", "generate", "play" — and then closes. That's all they do. You can open any of them in Notepad and read the whole thing.

**They're `.vbs` rather than `.bat` for one reason: no black window.** A `.bat` file opens a Command Prompt every time it runs, which flashes up and steals focus — unusable mid-game. A `.vbs` runs silently.

**Why `wscript.exe`?** It's the built-in Windows program that runs `.vbs` files, the same way Notepad opens `.txt` files. It lives in the `System32` folder because that's where Windows keeps its own programs — nothing unusual about pointing at it.

Your key-binding software can't launch a `.vbs` directly, so you point it at `wscript.exe` and pass the script as an argument. **That's why every entry below has the same file path** and only the argument changes.

### Setting them up

Using **Logitech G HUB** as the example:

**Assignments → SYSTEM → Launch Application → ADD APPLICATION**, once per key.

| Field | Value |
|---|---|
| FILE PATH | `C:\Windows\System32\wscript.exe` |
| ARGUMENTS | the `.vbs` file for that action |

**The five actions:**

| Action | Argument |
|---|---|
| Start recording | `C:\path\to\TTS\tts_start.vbs` |
| Stop and generate | `C:\path\to\TTS\tts_render.vbs` |
| Play the clip | `C:\path\to\TTS\tts_play.vbs` |
| Cancel a stuck render | `C:\path\to\TTS\tts_cancel.vbs` |
| Toggle mic passthrough | `C:\path\to\TTS\tts_passthrough.vbs` |

Then drag each entry onto the key you want.

> Use your real folder path, not `C:\path\to\TTS`.

### Optional: hold-to-talk

If your mouse or keyboard software can fire separate actions on **press** and **release**, you can hold a button to record instead of tapping two keys:

| Event | Argument |
|---|---|
| On press | `C:\path\to\TTS\tts_hold_start.vbs` |
| On release | `C:\path\to\TTS\tts_hold_end.vbs` |

Hold, talk, release — it records and generates in one gesture. With **Autoplay** on it plays by itself too.

*In G HUB this means a macro rather than a Launch Application assignment. The regular key bindings keep working alongside it.*

**Other software:** the principle is the same — run `wscript.exe` with the `.vbs` path as an argument. With **AutoHotkey v2**:

```
F13::Run "C:\path\to\TTS\tts_start.vbs"
F14::Run "C:\path\to\TTS\tts_render.vbs"
F15::Run "C:\path\to\TTS\tts_play.vbs"
F16::Run "C:\path\to\TTS\tts_cancel.vbs"
F17::Run "C:\path\to\TTS\tts_passthrough.vbs"
```

Bind your macro keys to F13–F17 (keys that don't physically exist, so nothing conflicts).

---

## Step 9 — Point your game at it

In your game's audio settings, set the **microphone** to **CABLE Output**.

That's it. The game now listens to the cable instead of your microphone.

### Use push-to-talk in the game

**Set your game's voice chat to push-to-talk, not open mic.** This matters more than it sounds.

With an open mic, **everything** that reaches the cable goes out live — including takes you're about to discard. Generate a bad one and the whole lobby hears it at the same time you do. Re-roll three times and they hear all three.

With push-to-talk you audition privately (turn **Monitor** on), re-roll until you're happy, then hold the key and play the good one.

> **Turn Monitor on while you're doing this.** Otherwise you can't hear your own takes at all, and you're picking blind.

> **Want to talk normally too?** Use the **Mic passthrough** button in the panel. It bridges your real microphone straight through to the cable, so the game hears your actual voice — then turn it off when you want only generated speech. The game never needs its audio device changed, which matters in titles that can't switch input without a restart.

---

## Using it

### The keys

| Action | Does |
|---|---|
| **Record** | Starts recording. Keeps going until you press Generate. |
| **Generate** | Stops recording and renders. **Press again for a different take** of the same recording. |
| **Play** | Plays it. Press repeatedly to replay. |
| **Cancel** | Kills a stuck generation. |
| **Passthrough** | Toggles your real mic through to the game. |

A typical round: **Record**, talk, **Generate**, listen on **Play**, not happy → **Generate** again, **Play**.

*Assign these to whichever keys suit you — nothing is hardcoded.*

### The control panel

**The Actions row** does the same four things as the keys — useful if you haven't bound any, or for testing each step:

| Button | Same as |
|---|---|
| **Record** | starts recording |
| **Generate** | stops recording and renders; press again to re-roll |
| **Play** | plays the current clip |
| **Cancel** | kills a stuck generation |

*These work whether or not you've set up macro keys, and you can mix the two freely.*

**The toggles above them:**

| Button | What it does |
|---|---|
| **Start / Stop service** | Runs the background service. Nothing works without it. |
| **Mic passthrough** | Bridges your real mic to the cable so the game hears you normally. Same as the passthrough key. |
| **Resample** | Matches the audio to your cable's sample rate. **Leave it on.** |
| **Autoplay** | Plays each clip the moment it finishes rendering, with no key press. **Use push-to-talk in the game if you turn this on** — see Step 9. |
| **Volume** | Cycles OFF → Normalize → Boost +6 → Boost +12. **Affects only what you hear**, never what the game hears. |
| **Monitor** | **ON** = lets you hear generated audio through your headphones. **OFF** = muted for you, but still plays through CABLE Output and into the game. |
| **CFG** | Overrides `cfg_scale` without touching ComfyUI. `workflow` uses whatever the workflow has set. |

**Volume and Monitor work together.** Turn Monitor on, then raise Volume — that's how you hear your own clips over a noisy game without changing anything for anyone else.

**Monitor also lets you vet a take before anyone hears it.** With push-to-talk in the game, you can render, listen privately, re-roll if it's wrong, and only then hold your talk key.

**About CFG:** the workflow ships at **1.0**, which copies the reference voice as closely as possible. If a reference clip is very expressive and you want something calmer and more consistent, try **3.0** or **4.0** — higher values flatten the emotional swings. Record once, then alternate **Generate** and **CFG** to compare values on the same take.

**Category and voice dropdowns** read from your `voices\` folder. Subfolders become categories, so `voices\male\` shows up as a **male** category.

**Refresh** re-reads that folder and your microphone list — use it after adding a clip or plugging in a device.

**Clean up** deletes only the files SpookyVoiceChanger has generated:

- your `ptt_*` recordings
- the `tts_voice_*` working copies of reference clips
- the clips it rendered this session

**Nothing else is touched.** Images, videos, your `voices\` library, and audio from other ComfyUI workflows all stay put — renders are tracked individually as they're created, not matched by file extension.

> Nothing needs cleaning for the tool to work — it already keeps only the last 20 recordings and ComfyUI clears its own temp folder on restart. The button is there if you'd rather not wait.

> Every toggle resets to off when you restart the panel.

**The panel log tells you what's happening:**

```
RECORDING [Your Mic] - press your render key when done
captured 2.84s (peak -14 dBFS)
delivery: normal conversational volume, steady pace, natural intonation
heard [12]: "Anyone got a spare bandage?"
READY in 2.3s - press your play key
```

That `heard` line is the text Breeze was given. If Whisper misheard a word, you'll spot it there before wasting a listen.

---

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| Output says **"Thank you"** | Your recording was silent. Whisper hallucinates this on silence. **Check your mic isn't muted** first, then see **If the microphone dropdown picks the wrong device** below. |
| Log says `near-silent`, names the right mic | The device opened but produced nothing. Mute switch, or a broken duplicate entry — see **If the microphone dropdown picks the wrong device** below. |
| **Every render is a different random voice** | `AUDIO_INPUT_NODE` points at the reference node instead of the speech node. Re-run `list_nodes.py`. |
| `'NoneType' object is not callable` | Breeze loader `attention` is on `auto`. Change it to `sdpa`, or `sageattention` if you have it installed. |
| `'NoneType' object has no attribute 'parameters'` | Model cache went bad, usually after cancelling mid-generation. **Restart ComfyUI.** |
| `Workflow not found` | `workflow_api.json` isn't in the project folder, or has a different name. |
| `No LoadAudio node found` | You exported the wrong workflow, or exported with Save instead of Export (API). |
| `no output device matching 'CABLE Input'` | VB-Cable isn't installed, or you skipped the reboot. |
| Browser URLs work, keys don't | The service is fine — it's the key binding. See **If your keys don't work** below. |
| **Nothing happens at all** | ComfyUI isn't running, or the service isn't started in the panel. Check ComfyUI's black console window is still open — closing it shuts ComfyUI down. |
| Worked yesterday, dead today | ComfyUI's console window was closed at some point. Start ComfyUI again. |
| First render takes ages | Normal. The models are loading into VRAM. Renders after that are fast. |
| `.vbs` file won't run, **"Access is denied"** | Windows blocked it as a downloaded file. Right-click → Properties → tick **Unblock** → Apply. Happens again after every re-download. |
| Security prompt every single launch | You left **"Always ask before opening this file"** ticked. Untick it next time the box appears. |
| Render runs long and comes out silent | A Breeze stall — it occasionally fails to stop on its own. **Hit Cancel** rather than waiting, then generate again. The tool auto-retries silent renders anyway, and `max_new_tokens` is already capped at 248 to limit how long a stall can run. |
| Output sounds **thin or hissy** | Your reference clip. Denoise it, or find a cleaner source. |

### If the microphone dropdown picks the wrong device

Windows lists the same physical microphone several times — once per audio API. Most of those entries work; occasionally one doesn't, and the panel can land on a broken one. The symptom is a recording that captures **silence** despite the log naming the right microphone.

**First, check the log line when you press Record:**

```
mic: [3] MME 44100 Hz, 1ch, float32
RECORDING [MAIN (2- RC-505mk2)] - press your render key when done
captured 1.55s - WARNING: near-silent (peak -81 dBFS)
```

That `near-silent` warning means the device opened but produced nothing.

**Things to rule out first:**

- **Is the mic physically muted?** A mute switch produces exactly this. It's the most common cause by far.
- **Pick a different entry** in the Microphone dropdown and try again.

**If it's still silent, find out which devices actually work.** Open a command prompt in your TTS folder (address bar → type `cmd` → Enter) and run:

```
python tts_service.py --probe
```

It tries every input device on your system and reports which ones open, with a summary at the end:

```
Usable input devices:

  [1] MAIN (2- RC-505mk2)  (MME, 44100 Hz, 1ch)
  [19] MAIN (2- RC-505mk2)  (Windows DirectSound, 44100 Hz, 1ch)
```

> **Stop the service in the panel first**, or the device will be busy and everything reports as failed.

### Setting the microphone by hand

The panel writes your choice into a file called **`mic.txt`** in the TTS folder. You can edit it directly if the dropdown isn't cooperating.

Open it in Notepad and put in **either**:

- **Part of the device name** — `MAIN`, or `Headset`. Matching is case-insensitive and partial, so a fragment is enough.
- **A device number** from the probe output — `1`

Save the file. **No restart needed** — it's read each time you start recording.

> **Prefer a name over a number.** Device numbers shift when you plug in a monitor or change your default audio device; names don't.

**An empty or missing `mic.txt` means "use the Windows default microphone."** That's fine normally, but it causes trouble once you set CABLE Output as your default input for a game — the tool would then record the cable instead of you. Always name your real microphone explicitly.

---

### If your keys don't work

The browser test in Step 7 proves the service is working. So if the URLs respond but your keys do nothing, the problem is entirely in how the key is set up. Work through these in order:

**1. Does the file work on its own?**

Double-click `tts_start.vbs` in File Explorer. Watch the panel log.

- **Log says `RECORDING`** → the file is fine, skip to point 3
- **Nothing happens** → continue to point 2

**2. Is the file blocked?**

Right-click it → **Properties** → tick **Unblock** at the bottom → **Apply**. Do this for every `.vbs` file. Try double-clicking again.

**3. Check the FILE PATH field**

It must be `wscript.exe`, **not** the `.vbs` file:

```
C:\Windows\System32\wscript.exe
```

*Putting the `.vbs` in this field is the single most common mistake. It looks right, and it silently does nothing.*

**4. Check the ARGUMENTS field**

It must be the **full path**, starting with a drive letter:

```
C:\Users\yourname\Desktop\TTS\tts_start.vbs
```

- **Not** just `tts_start.vbs`
- **No quotes** around it unless your path contains spaces
- Easiest way to get it exactly right: **shift + right-click the file → Copy as path**, then paste (and delete the quotes it adds if there are no spaces in your path)

**5. Is the assignment actually on a key?**

Creating the entry isn't enough — you have to **drag it onto a key** on the picture of your device. Check the key shows your macro's name next to it.

**6. Is the right profile active?**

G HUB and similar software use per-application profiles. If you set it up on the Desktop profile but your game has its own, the key won't fire in-game. Check the profile dropdown at the top.

---

**When something breaks, read the panel log first.** It names the failing node and the actual error.

---

## Notes

**The generated voice quality depends almost entirely on your reference clip.** Time spent finding a clean one beats any amount of settings tweaking.

**The first render after starting ComfyUI is slow**, then everything speeds up. The models load into VRAM once and stay there. A render that takes 40 seconds cold will take around 2 seconds warm.

**Leave ComfyUI's black console window running.** Closing it shuts ComfyUI down. The browser tab can be closed safely.

**Recordings are kept temporarily.** The last 20 land in ComfyUI's `input` folder and older ones delete themselves. The **Clean up** button clears them immediately, along with rendered clips, if you'd rather not leave them lying around.

**Switching voices takes effect immediately** — pick from the dropdown, next render uses it. No restart, no re-export.

**Re-export `workflow_api.json`** any time you change the workflow structure in ComfyUI. The script reads the exported file, not what's on your screen.
