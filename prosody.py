#!/usr/bin/env python3
"""
Turns a voice recording into a Breeze TTS 2 Voice Direction instruction.

Measures three things that survive across speakers:

    loudness  - how hard you were pushing
    rate      - roughly how many syllables per second
    pitch     - how much your intonation moved, in semitones

and writes a plain-English instruction from them.

Run it on a wav to see what it would produce:

    python prosody.py somefile.wav
"""

import sys
import numpy as np

# Pitch search range in Hz. Covers low male to high female speech.
F0_MIN = 70
F0_MAX = 350

FRAME_MS = 40
HOP_MS = 20


# ------------------------------------------------------------- measurement

def frame_signal(x, sr):
    frame = int(sr * FRAME_MS / 1000)
    hop = int(sr * HOP_MS / 1000)
    if len(x) < frame:
        return np.empty((0, frame)), frame, hop
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    return x[idx], frame, hop


def loudness_db(x, sr):
    """RMS of the speech portion only, ignoring gaps. Absolute dBFS."""
    frames, _, _ = frame_signal(x, sr)
    if len(frames) == 0:
        return -99.0
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-12
    db = 20 * np.log10(rms)
    # Average the top 30% of frames - that's speech, not silence.
    speech = db[db > np.percentile(db, 70)]
    return float(speech.mean()) if len(speech) else float(db.max())


def voiced_ratio(x, sr):
    """Fraction of speech frames with clear vocal-fold periodicity.

    Whispering has almost none - the vocal folds aren't vibrating - so
    this separates a genuine whisper from merely talking softly.
    """
    frames, frame, _ = frame_signal(x, sr)
    if len(frames) == 0:
        return 0.0

    lag_min = int(sr / F0_MAX)
    lag_max = min(int(sr / F0_MIN), frame - 1)
    if lag_max <= lag_min:
        return 0.0

    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-12
    gate = np.percentile(rms, 60)
    window = np.hanning(frame)

    considered = voiced = 0
    for f, level in zip(frames, rms):
        if level < gate:
            continue
        considered += 1
        seg = (f - f.mean()) * window
        corr = np.correlate(seg, seg, mode="full")[frame - 1:]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        region = corr[lag_min:lag_max]
        if len(region) and region.max() >= 0.3:
            voiced += 1

    return voiced / considered if considered else 0.0


def estimate_f0(x, sr):
    """Per-frame pitch by autocorrelation. Returns voiced F0 values in Hz."""
    frames, frame, _ = frame_signal(x, sr)
    if len(frames) == 0:
        return np.array([])

    lag_min = int(sr / F0_MAX)
    lag_max = min(int(sr / F0_MIN), frame - 1)
    if lag_max <= lag_min:
        return np.array([])

    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-12
    voiced_gate = np.percentile(rms, 60)

    out = []
    window = np.hanning(frame)
    for f, level in zip(frames, rms):
        if level < voiced_gate:
            continue
        seg = (f - f.mean()) * window
        corr = np.correlate(seg, seg, mode="full")[frame - 1:]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        region = corr[lag_min:lag_max]
        if len(region) == 0:
            continue
        lag = int(np.argmax(region)) + lag_min
        # Weak periodicity means it wasn't really voiced.
        if corr[lag] < 0.3:
            continue
        out.append(sr / lag)

    return np.array(out)


def pitch_movement(f0):
    """Spread of intonation in semitones. Speaker-independent."""
    if len(f0) < 5:
        return 0.0
    semitones = 12 * np.log2(f0 / np.median(f0))
    # Interquartile spread resists octave errors better than std.
    return float(np.percentile(semitones, 75) - np.percentile(semitones, 25))


def syllable_rate(x, sr):
    """Rough syllables per second from peaks in the energy envelope."""
    frames, _, hop = frame_signal(x, sr)
    if len(frames) < 3:
        return 0.0

    env = np.sqrt((frames ** 2).mean(axis=1))
    if env.max() <= 0:
        return 0.0
    env = env / env.max()

    # Light smoothing so one syllable isn't counted twice.
    kernel = np.ones(3) / 3
    env = np.convolve(env, kernel, mode="same")

    threshold = max(0.15, env.mean() * 0.6)
    peaks = 0
    for i in range(1, len(env) - 1):
        if env[i] > threshold and env[i] >= env[i - 1] and env[i] > env[i + 1]:
            peaks += 1

    seconds = len(x) / sr
    return peaks / seconds if seconds > 0 else 0.0


def analyse(x, sr):
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)

    peak = float(np.abs(x).max())

    # Deliberately NOT normalised. Your mic gain is fixed, so the absolute
    # level is exactly what tells loud apart from quiet.
    f0 = estimate_f0(x, sr)

    return {
        "loudness_db": loudness_db(x, sr),
        "voiced": voiced_ratio(x, sr),
        "rate": syllable_rate(x, sr),
        "movement": pitch_movement(f0),
        "f0_median": float(np.median(f0)) if len(f0) else 0.0,
        "peak_dbfs": 20 * np.log10(peak) if peak > 0 else -99.0,
        "seconds": len(x) / sr,
    }


# ------------------------------------------------------------- description

def describe(m):
    """Build a Voice Direction instruction from the measurements."""
    parts = []

    # A real whisper has no vocal-fold vibration, however loud it sounds.
    # Check that before anything else.
    if m["voiced"] < 0.25 and m["loudness_db"] < -18:
        parts.append("whispering, breathy and close to the microphone")
    else:
        db = m["loudness_db"]
        if db > -14:
            parts.append("loud and forceful, projecting")
        elif db > -20:
            parts.append("raised and energetic")
        elif db > -30:
            parts.append("normal conversational volume")
        elif db > -40:
            parts.append("quiet and soft")
        else:
            parts.append("very quiet, hushed")

    # Speaking rate.
    rate = m["rate"]
    if rate > 5.0:
        parts.append("speaking quickly, words tumbling out")
    elif rate > 3.6:
        parts.append("brisk pace")
    elif rate > 2.2:
        parts.append("steady pace")
    else:
        parts.append("slow and deliberate, leaving space between words")

    # Intonation range.
    move = m["movement"]
    if move > 6.0:
        parts.append("highly animated intonation, big pitch swings")
    elif move > 3.5:
        parts.append("expressive intonation")
    elif move > 1.8:
        parts.append("natural intonation")
    else:
        parts.append("flat, level delivery with little pitch variation")

    return ", ".join(parts)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    import soundfile as sf

    x, sr = sf.read(sys.argv[1], always_2d=True)
    m = analyse(x, sr)

    print(f"\n  duration   {m['seconds']:.2f}s")
    print(f"  peak       {m['peak_dbfs']:.1f} dBFS")
    print(f"  loudness   {m['loudness_db']:.1f} dB (normalised)")
    print(f"  rate       {m['rate']:.2f} syllables/sec")
    print(f"  movement   {m['movement']:.2f} semitones")
    print(f"  pitch      {m['f0_median']:.0f} Hz")
    print(f"\n  instruction:\n    {describe(m)}\n")


if __name__ == "__main__":
    main()
