import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import YouTubeTranscriptApiException
from requests import RequestException

from sourcewise.config import MAX_MEDIA_BYTES, MAX_TEXT, MAX_VIDEO_SECONDS
from sourcewise.domain import Material, Passage, SourceError

_WHISPER = None
_MODEL_LOCK = threading.Lock()


def video_id(url):
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.port:
            raise ValueError
        if parts.hostname == "youtu.be":
            value = parts.path.strip("/")
        elif parts.hostname in {"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"}:
            value = parse_qs(parts.query).get("v", [""])[0] if parts.path == "/watch" else (
                parts.path.split("/")[2] if re.fullmatch(r"/(?:shorts|embed|live)/[^/]+/?", parts.path) else ""
            )
        else:
            raise ValueError
        if not re.fullmatch(r"[\w-]{11}", value, flags=re.ASCII):
            raise ValueError
        return value
    except ValueError as exc:
        raise SourceError("Enter a YouTube video URL, such as https://www.youtube.com/watch?v=VIDEO_ID.") from exc


def timestamp(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def timed_passages(segments, href):
    group = []
    words = 0
    total = 0
    for start, end, text in segments:
        text = " ".join(text.split())
        if not text:
            continue
        total += len(text)
        if total > MAX_TEXT:
            raise SourceError("The recovered transcript exceeds 200,000 characters.")
        if group and (words >= 260 or end - group[0][0] > 100):
            yield make_passage(group, href)
            group, words = [], 0
        group.append((start, end, text))
        words += len(text.split())
    if group:
        yield make_passage(group, href)


def make_passage(group, href):
    start, end = int(group[0][0]), max(int(group[0][0]), int(group[-1][1]))
    target = f"{href}&t={start}s" if href else ""
    return Passage(" ".join(part[2] for part in group), f"{timestamp(start)}–{timestamp(end)}", target, start, end)


def captions(identifier):
    api = YouTubeTranscriptApi()
    try:
        track_list = api.list(identifier)
        tracks = list(track_list)
        preferred = os.getenv("YOUTUBE_CAPTION_LANGUAGES", "en").split(",")
        caption = next((t for lang in preferred for t in tracks if t.language_code == lang.strip()), None)
        caption = caption or next(iter(tracks), None)
        if not caption:
            return []
        return [(s.start, s.start + s.duration, s.text) for s in caption.fetch() if s.text.strip(" []\n")]
    except (YouTubeTranscriptApiException, RequestException, StopIteration):
        return []


def title_for(identifier):
    import httpx

    url = f"https://www.youtube.com/watch?v={identifier}"
    try:
        response = httpx.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=5)
        if response.is_success:
            return str(response.json().get("title") or f"YouTube video {identifier}")[:180]
    except (httpx.HTTPError, ValueError):
        pass
    return f"YouTube video {identifier}"


def require_media(tool):
    if not shutil.which(tool):
        raise SourceError(f"{tool} is needed for captionless videos. Install the media dependencies or use Docker.")


def download(url, folder, visual=False):
    require_media("ffmpeg")
    args = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-progress",
        "--no-warnings", "--no-cache-dir", "--restrict-filenames", "--socket-timeout", "15",
        "--retries", "1", "--fragment-retries", "1", "--no-part", "--max-filesize", str(MAX_MEDIA_BYTES),
        "--match-filter", f"duration <= {MAX_VIDEO_SECONDS} & !is_live",
        "--format", "worst[height<=480]/worst" if visual else "bestaudio/best",
        "--output", str(folder / ("visual.%(ext)s" if visual else "audio.%(ext)s")),
        "--print", "after_move:filepath", "--no-simulate",
    ]
    if shutil.which("node"):
        args.extend(["--js-runtimes", "node"])
    cookies = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookies:
        args.extend(["--cookies", cookies])
    try:
        result = subprocess.run([*args, "--", url], capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            for line in reversed(result.stdout.splitlines()):
                candidate = Path(line)
                if candidate.is_file() and candidate.resolve().parent == folder.resolve():
                    if candidate.stat().st_size <= MAX_MEDIA_BYTES:
                        return candidate
                    candidate.unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        pass
    raise SourceError("YouTube did not provide downloadable media. Try uploading a video or audio file you can access.")


def duration_for(path):
    require_media("ffprobe")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
             "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=15,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        if 0 < duration <= MAX_VIDEO_SECONDS:
            return duration
        raise SourceError("Use media under two hours long.")
    except (subprocess.SubprocessError, KeyError, ValueError) as exc:
        raise SourceError("The media file could not be read. Try MP4, WebM, MP3, M4A, WAV, or OGG.") from exc


def speech_segments(path):
    global _WHISPER
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise SourceError("Install requirements-media.txt to transcribe videos without captions, or run the Docker image.") from error
    require_media("ffmpeg")
    # Produce a fixed-format local audio stream before passing untrusted media to Whisper.
    with tempfile.TemporaryDirectory(prefix="sourcewise-speech-") as directory:
        audio = Path(directory) / "audio.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(path),
                 "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)],
                capture_output=True, check=True, timeout=180,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        try:
            with wave.open(str(audio), "rb") as stream:
                samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
            samples = samples.astype(np.float32) / 32768.0
            with _MODEL_LOCK:
                if _WHISPER is None:
                    device = os.getenv("WHISPER_DEVICE", "cpu")
                    _WHISPER = WhisperModel(
                        os.getenv("WHISPER_MODEL", "small"), device=device,
                        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8" if device == "cpu" else "float16"),
                        cpu_threads=4,
                    )
                segments, _ = _WHISPER.transcribe(samples, vad_filter=True, beam_size=3)
                return [(s.start, s.end, s.text) for s in segments if s.text.strip()]
        except Exception as exc:
            raise SourceError("Speech transcription failed. Check the Whisper model cache, disk space, and device settings.") from exc


def frame_text(path, duration, folder):
    if not shutil.which("tesseract") or not shutil.which("ffmpeg"):
        return []
    step = max(12, int(duration / 45) + 1)
    frames = folder / "frames"
    frames.mkdir()
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(path),
             "-an", "-vf", f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{step})',scale='min(1280,iw)':-2",
             "-fps_mode", "vfr", "-frames:v", "45",
             str(frames / "%03d.jpg")], capture_output=True, timeout=110, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    segments = []
    for index, image in enumerate(sorted(frames.glob("*.jpg"))):
        try:
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", os.getenv("OCR_LANGUAGE", "eng")],
                capture_output=True, text=True, check=True, timeout=8,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        text = " ".join(result.stdout.split())
        if len(text) >= 16 and (not segments or difflib.SequenceMatcher(None, segments[-1][2], text).ratio() < .86):
            segments.append((index * step, min(duration, (index + 1) * step), text))
    return segments


def load(url, path, filename, progress):
    identifier = video_id(url) if url else ""
    href = f"https://www.youtube.com/watch?v={identifier}" if identifier else ""
    title = title_for(identifier) if identifier else Path(filename).stem[:180]
    if href and not path:
        progress("Checking for YouTube captions")
        segments = captions(identifier)
        if passages := list(timed_passages(segments, href)):
            return Material(title, "YouTube captions", passages)
    with tempfile.TemporaryDirectory(prefix="sourcewise-video-") as directory:
        folder = Path(directory)
        if not path:
            progress("Downloading audio for transcription")
        media = Path(path) if path else download(href, folder)
        duration = duration_for(media)
        progress("Transcribing the audio with Whisper")
        speech_error = None
        try:
            segments = speech_segments(media)
        except SourceError as exc:
            speech_error, segments = exc, []
        if passages := list(timed_passages(segments, href)):
            return Material(title, "Whisper audio transcription", passages)
        progress("Looking for text in video frames")
        if not path:
            try:
                media = download(href, folder, visual=True)
            except SourceError:
                if speech_error:
                    raise speech_error
                raise
        if passages := list(timed_passages(frame_text(media, duration, folder), href)):
            return Material(title, "Video frame OCR", passages, notes=[
                "Speech was unavailable. The summary uses text recovered from sampled frames."
            ])
        if speech_error:
            raise speech_error
        raise SourceError("No speech or readable on-screen text was recovered from this media.")
