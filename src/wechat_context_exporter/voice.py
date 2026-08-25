from __future__ import annotations

import hashlib
import json
import os
import tempfile
import wave
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from .models import Message, MessageType


ProgressCallback = Callable[[int, int, str], None]


def default_voice_model() -> str:
    return os.environ.get("WECHAT_AI_MEMORY_WHISPER_MODEL", "small")


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "WeChatAIMemory"


def voice_placeholder(duration_ms: int | None, available: bool = True) -> str:
    duration = f" · {max(1, round(duration_ms / 1000))} 秒" if duration_ms else ""
    state = "待转写" if available else "音频暂不可读"
    return f"[语音消息{duration} · {state}]"


def audio_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VoiceTranscriptCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "voice-transcripts"

    def load(self, audio_path: Path, model: str | None = None) -> str | None:
        path = self._path(audio_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or (model and payload.get("model") != model):
            return None
        transcript = payload.get("transcript")
        return transcript.strip() if isinstance(transcript, str) and transcript.strip() else None

    def save(self, audio_path: Path, transcript: str, model: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(audio_path)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"transcript": transcript, "model": model}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)

    def _path(self, audio_path: Path) -> Path:
        return self.root / f"{audio_fingerprint(audio_path)}.json"


def decode_silk_to_wav(source: Path, destination: Path, sample_rate: int = 24_000) -> Path:
    try:
        import pysilk
    except ImportError as exc:
        raise RuntimeError("当前软件包缺少微信语音解码组件，请重新安装最新版。") from exc

    pcm = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with source.open("rb") as silk_stream:
        pysilk.decode(silk_stream, pcm, sample_rate)
    pcm.seek(0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.read())
    pcm.close()
    return destination


class VoiceTranscriber:
    def __init__(
        self,
        model_name: str | None = None,
        cache: VoiceTranscriptCache | None = None,
        model_root: Path | None = None,
    ) -> None:
        self.model_name = model_name or default_voice_model()
        self.cache = cache or VoiceTranscriptCache()
        self.model_root = model_root or app_data_dir() / "models"

    def transcribe_messages(
        self,
        messages: Iterable[Message],
        progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[Message]:
        result = list(messages)
        targets = [
            (index, message)
            for index, message in enumerate(result)
            if message.type is MessageType.VOICE and message.voice_path and message.voice_path.is_file()
        ]
        pending: list[tuple[int, Message]] = []
        for index, message in targets:
            cached = message.transcript or self.cache.load(message.voice_path, self.model_name)
            if cached:
                result[index] = replace(message, content=cached, transcript=cached)
            else:
                pending.append((index, message))
        if not pending:
            return result

        if progress:
            progress(0, len(pending), "正在准备本地语音模型，首次使用需要下载一次")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("当前软件包缺少本地语音转写组件，请重新安装最新版。") from exc

        self.model_root.mkdir(parents=True, exist_ok=True)
        model = WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(self.model_root),
        )
        with tempfile.TemporaryDirectory(prefix="wechat-memory-voice-") as temp_name:
            for current, (index, message) in enumerate(pending, start=1):
                if cancelled and cancelled():
                    break
                if progress:
                    progress(current - 1, len(pending), f"正在转写语音 {current}/{len(pending)}")
                wav_path = Path(temp_name) / f"{current:05d}.wav"
                decode_silk_to_wav(message.voice_path, wav_path)
                segments, _info = model.transcribe(
                    str(wav_path),
                    language="zh",
                    beam_size=5,
                    vad_filter=True,
                )
                transcript = "".join(segment.text.strip() for segment in segments).strip()
                if not transcript:
                    transcript = "[语音内容未识别]"
                self.cache.save(message.voice_path, transcript, self.model_name)
                result[index] = replace(message, content=transcript, transcript=transcript)
                if progress:
                    progress(current, len(pending), f"已转写语音 {current}/{len(pending)}")
        return result
