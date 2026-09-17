"""Records a Discord session straight from your PC.

Captures two tracks at the same time:
  * your microphone      -> you
  * your speaker output  -> everyone else in the Discord call (WASAPI loopback)

Each track is written to disk as it records, so a 4-hour session never has to
fit in memory. Press Ctrl+C to stop.

For per-player speaker labels, use the Craig Discord bot instead (see README);
this recorder is the zero-setup option.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
import wave
from pathlib import Path

from .config import RECORDINGS_DIR


def _require_soundcard():
    try:
        import soundcard  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Recording needs the 'soundcard' package: pip install soundcard"
        ) from exc


def list_devices() -> None:
    _require_soundcard()
    import soundcard as sc

    print("Microphones:")
    for m in sc.all_microphones():
        print(f"  - {m.name}")
    print("\nSpeakers (for loopback):")
    for s in sc.all_speakers():
        print(f"  - {s.name}")
    print(f"\nDefault mic:     {sc.default_microphone().name}")
    print(f"Default speaker: {sc.default_speaker().name}")


def _track_worker(device, out_path: Path, rate: int, stop: threading.Event,
                  errors: list, label: str) -> None:
    import numpy as np

    block = rate // 2  # half-second blocks
    try:
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            with device.recorder(samplerate=rate, channels=1, blocksize=block) as rec:
                while not stop.is_set():
                    data = rec.record(numframes=block)
                    mono = data[:, 0] if data.ndim > 1 else data
                    pcm = np.clip(mono, -1.0, 1.0)
                    wf.writeframes((pcm * 32767).astype("<i2").tobytes())
    except Exception as exc:  # pragma: no cover - hardware specific
        errors.append(f"{label}: {exc}")
        stop.set()


def _find(devices, name_part: str | None, default):
    if not name_part:
        return default
    for d in devices:
        if name_part.lower() in d.name.lower():
            return d
    raise SystemExit(f"No audio device matching '{name_part}'. Run: python scribe.py devices")


def record(cfg: dict, session_label: str | None = None,
           mic_name: str | None = None, speaker_name: str | None = None) -> Path:
    """Record until Ctrl+C. Returns the folder holding the track files."""
    _require_soundcard()
    import soundcard as sc

    rate = int(cfg["recording"]["sample_rate"])
    me = cfg["recording"].get("my_name") or "Me"

    mic = _find(sc.all_microphones(), mic_name, sc.default_microphone())
    spk = _find(sc.all_speakers(), speaker_name, sc.default_speaker())
    loopback = sc.get_microphone(id=str(spk.name), include_loopback=True)

    stamp = session_label or dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = RECORDINGS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    stop = threading.Event()
    errors: list[str] = []
    tracks = [
        (mic, out_dir / f"1-{me}.wav", "microphone"),
        (loopback, out_dir / "2-Table.wav", "speaker loopback"),
    ]
    threads = [
        threading.Thread(target=_track_worker, args=(dev, path, rate, stop, errors, label), daemon=True)
        for dev, path, label in tracks
    ]

    print(f"Recording mic:      {mic.name}")
    print(f"Recording speakers: {spk.name}")
    print(f"Saving to:          {out_dir}")
    print("Tell the table you're recording! Press Ctrl+C to stop.\n")

    for t in threads:
        t.start()
    started = time.time()
    try:
        while not stop.is_set():
            elapsed = int(time.time() - started)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            print(f"\r  ● REC {h:02d}:{m:02d}:{s:02d}", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        print("\nStopped.")

    if errors:
        print("Problems while recording:\n  " + "\n  ".join(errors))
    return out_dir
