from __future__ import annotations

import json
import io
import wave
from datetime import datetime

from wechat_context_exporter.models import Message, MessageType
import pysilk

from wechat_context_exporter.voice import (
    VoiceTranscriptCache,
    VoiceTranscriber,
    decode_silk_to_wav,
    voice_placeholder,
)


def test_voice_transcript_cache_updates_messages_without_loading_model(tmp_path) -> None:
    audio = tmp_path / "voice.silk"
    audio.write_bytes(b"\x02#!SILK_V3\nvoice")
    cache = VoiceTranscriptCache(tmp_path / "transcripts")
    cache.save(audio, "这是缓存的语音文字", "small")
    message = Message(
        "voice-1",
        "chat",
        "张三",
        datetime(2026, 8, 25, 9),
        MessageType.VOICE,
        voice_placeholder(3200),
        audio_path=audio,
        duration_ms=3200,
    )

    result = VoiceTranscriber(model_name="small", cache=cache).transcribe_messages([message])

    assert result[0].content == "这是缓存的语音文字"
    assert result[0].transcript == "这是缓存的语音文字"
    payload = json.loads(next((tmp_path / "transcripts").glob("*.json")).read_text(encoding="utf-8"))
    assert payload["model"] == "small"


def test_voice_placeholder_describes_duration_and_availability() -> None:
    assert voice_placeholder(5920) == "[语音消息 · 6 秒 · 待转写]"
    assert voice_placeholder(None, False) == "[语音消息 · 音频暂不可读]"


def test_silk_audio_decodes_to_mono_wav(tmp_path) -> None:
    silk = io.BytesIO()
    pysilk.encode(io.BytesIO(b"\0\0" * 24_000), silk, 24_000, 20_000)
    source = tmp_path / "voice.silk"
    source.write_bytes(silk.getvalue())

    output = decode_silk_to_wav(source, tmp_path / "voice.wav")

    with wave.open(str(output), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        assert wav.getnframes() == 24_000
