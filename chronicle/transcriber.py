"""Turns a recording into a speaker-labelled transcript using Whisper, locally.

Accepts:
  * a single audio/video file (mp3, wav, m4a, flac, ogg, mp4, mkv, ...)
  * a folder or .zip of per-speaker tracks (Craig bot, or this repo's recorder)
  * an existing transcript (.txt, .vtt, .srt) - used as-is
"""
from __future__ import annotations

import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
              ".mp4", ".mkv", ".webm", ".mov"}
TEXT_EXTS = {".txt", ".vtt", ".srt", ".md"}


@dataclass
class Segment:
    start: float
    end: float
    speaker: str | None
    text: str


def speaker_from_filename(path: Path) -> str:
    """'1-kingkale.flac' -> 'kingkale', '3-Big_Dave_0.flac' -> 'Big_Dave'."""
    stem = path.stem
    stem = re.sub(r"^\d+[-_ ]", "", stem)          # Craig track number
    stem = re.sub(r"(#\d{1,4}|_\d{1,4})$", "", stem)  # discriminator / split suffix
    return stem or path.stem


def map_speaker(raw: str | None, speakers: dict) -> str | None:
    if raw is None:
        return None
    lookup = {str(k).lower(): v for k, v in (speakers or {}).items()}
    return lookup.get(raw.lower(), raw)


def collect_tracks(source: Path, workdir: Path) -> list[Path]:
    """Return the audio files to transcribe (extracting zips into workdir)."""
    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as zf:
            zf.extractall(workdir)
        source = workdir
    if source.is_dir():
        tracks = sorted(p for p in source.rglob("*")
                        if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
        if not tracks:
            raise SystemExit(f"No audio files found in {source}")
        return tracks
    if source.suffix.lower() in AUDIO_EXTS:
        return [source]
    raise SystemExit(f"Don't know how to read {source.name}")


def fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def merge_segments(segments: list[Segment], gap: float = 2.0) -> list[Segment]:
    """Sort by time and glue back-to-back lines from the same speaker together."""
    merged: list[Segment] = []
    for seg in sorted(segments, key=lambda s: s.start):
        text = seg.text.strip()
        if not text:
            continue
        prev = merged[-1] if merged else None
        if prev and prev.speaker == seg.speaker and seg.start - prev.end <= gap:
            prev.text = f"{prev.text} {text}"
            prev.end = max(prev.end, seg.end)
        else:
            merged.append(Segment(seg.start, seg.end, seg.speaker, text))
    return merged


def render_transcript(segments: list[Segment]) -> str:
    lines = []
    for s in segments:
        who = f"{s.speaker}: " if s.speaker else ""
        lines.append(f"[{fmt_ts(s.start)}] {who}{s.text}")
    return "\n".join(lines) + "\n"


def _load_model(wcfg: dict):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Transcription needs faster-whisper: pip install faster-whisper") from exc

    size = wcfg.get("model", "small.en")
    device = wcfg.get("device", "auto")
    if device == "cpu":
        return WhisperModel(size, device="cpu", compute_type="int8")
    try:
        return WhisperModel(size, device=device, compute_type="default")
    except Exception as exc:  # GPU libs missing etc.
        print(f"  (couldn't use device '{device}': {exc}; falling back to CPU)")
        return WhisperModel(size, device="cpu", compute_type="int8")


def _is_gpu_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("cuda", "cublas", "cudnn", "gpu"))


def _transcribe_track(model, track: Path, wcfg: dict, name: str | None) -> list[Segment]:
    segs, info = model.transcribe(
        str(track),
        language=wcfg.get("language") or None,
        vad_filter=True,                   # skips the long silences in per-speaker tracks
        vad_parameters={"min_silence_duration_ms": 700},
        initial_prompt=wcfg.get("initial_prompt") or None,
        condition_on_previous_text=False,  # avoids runaway repetition on long audio
    )
    out: list[Segment] = []
    for s in segs:  # generator: the real work happens while iterating
        out.append(Segment(s.start, s.end, name, s.text))
        if len(out) % 50 == 0:
            print(f"\r    ...{fmt_ts(s.end)} of {fmt_ts(info.duration)}", end="", flush=True)
    return out


def transcribe(source: Path, cfg: dict, out_file: Path) -> Path:
    """Transcribe `source` and write a text transcript to `out_file`."""
    source = Path(source)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if source.is_file() and source.suffix.lower() in TEXT_EXTS:
        out_file.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        print(f"Using existing transcript {source.name}")
        return out_file

    wcfg = cfg["whisper"]
    speakers = cfg.get("speakers", {})

    with tempfile.TemporaryDirectory() as tmp:
        tracks = collect_tracks(source, Path(tmp))
        multitrack = len(tracks) > 1
        print(f"Loading Whisper model '{wcfg.get('model')}' ...")
        model = _load_model(wcfg)

        all_segments: list[Segment] = []
        for i, track in enumerate(tracks, 1):
            raw_name = speaker_from_filename(track) if multitrack else None
            name = map_speaker(raw_name, speakers)
            label = f" ({name})" if name else ""
            print(f"[{i}/{len(tracks)}] Transcribing {track.name}{label} ...")
            t0 = time.time()
            try:
                found = _transcribe_track(model, track, wcfg, name)
            except Exception as exc:
                if not _is_gpu_error(exc):
                    raise
                print(f"    GPU problem ({exc}); switching to CPU, this will be slower.")
                model = _load_model({**wcfg, "device": "cpu"})
                found = _transcribe_track(model, track, wcfg, name)
            all_segments.extend(found)
            print(f"\r    done: {len(found)} lines in {int(time.time() - t0)}s" + " " * 20)

    text = render_transcript(merge_segments(all_segments))
    out_file.write_text(text, encoding="utf-8")
    print(f"Transcript saved: {out_file}")
    return out_file
