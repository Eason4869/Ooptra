"""语音 Agent / VOICE_API 配置加载。config.py 缺字段时用默认值，不阻塞启动。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value


def _get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    value = cfg.get(key, default)
    return default if value is None else value


@dataclass
class VoiceAgentSettings:
    enabled: bool = False
    backend: str = "gemini_live"
    persona: str = "你是 Oopz 语音频道助手，说话简洁友好，像在语音房里自然聊天。"
    area: str = ""
    channel: str = ""
    auto_join: bool = False
    barge_in: bool = True
    vad_mode: str = "local"
    listen_only_uids: list[str] = field(default_factory=list)
    reply_text_to_channel: bool = False
    sample_rate_in: int = 16000
    sample_rate_out: int = 24000
    silence_ms: int = 700
    max_utterance_ms: int = 15000

    # MiMo 级联
    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_asr_model: str = "mimo-v2.5-asr"
    mimo_llm_model: str = "mimo-v2.6-flash"
    mimo_tts_model: str = "mimo-v2.5-tts"
    mimo_tts_voice: str = "冰糖"

    # Gemini Live
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-live-001"
    gemini_voice: str = "Puck"

    # OpenAI Realtime（骨架）
    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-4o-mini-realtime-preview"

    memory_path: str = "data/voice_memory.jsonl"
    memory_max_turns: int = 30


@dataclass
class VoiceApiSettings:
    # 独立端口默认关闭：语音接口已合并到 WebUI /api/*
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 3091
    token: str = ""


def load_voice_agent_settings() -> tuple[VoiceAgentSettings, VoiceApiSettings]:
    try:
        import config as runtime_config
    except Exception:
        runtime_config = None

    agent_raw = dict(getattr(runtime_config, "VOICE_AGENT_CONFIG", None) or {})
    api_raw = dict(getattr(runtime_config, "VOICE_API_CONFIG", None) or {})

    mimo = dict(_get(agent_raw, "mimo", {}) or {})
    gemini = dict(_get(agent_raw, "gemini", {}) or {})
    openai = dict(_get(agent_raw, "openai", {}) or {})

    agent = VoiceAgentSettings(
        enabled=bool(_get(agent_raw, "enabled", False)),
        backend=str(_get(agent_raw, "backend", "gemini_live") or "gemini_live"),
        persona=str(_get(agent_raw, "persona", VoiceAgentSettings.persona)),
        area=str(_get(agent_raw, "area", "") or ""),
        channel=str(_get(agent_raw, "channel", "") or ""),
        auto_join=bool(_get(agent_raw, "auto_join", False)),
        barge_in=bool(_get(agent_raw, "barge_in", True)),
        vad_mode=str(_get(agent_raw, "vad_mode", "local") or "local"),
        listen_only_uids=[str(x) for x in (_get(agent_raw, "listen_only_uids", []) or [])],
        reply_text_to_channel=bool(_get(agent_raw, "reply_text_to_channel", False)),
        sample_rate_in=int(_get(agent_raw, "sample_rate_in", 16000)),
        sample_rate_out=int(_get(agent_raw, "sample_rate_out", 24000)),
        silence_ms=int(_get(agent_raw, "silence_ms", 700)),
        max_utterance_ms=int(_get(agent_raw, "max_utterance_ms", 15000)),
        mimo_api_key=_env("MIMO_API_KEY", str(mimo.get("api_key", "") or "")),
        mimo_base_url=str(mimo.get("base_url", VoiceAgentSettings.mimo_base_url) or VoiceAgentSettings.mimo_base_url),
        mimo_asr_model=str(mimo.get("asr_model", "mimo-v2.5-asr") or "mimo-v2.5-asr"),
        mimo_llm_model=str(mimo.get("llm_model", "mimo-v2.6-flash") or "mimo-v2.6-flash"),
        mimo_tts_model=str(mimo.get("tts_model", "mimo-v2.5-tts") or "mimo-v2.5-tts"),
        mimo_tts_voice=str(mimo.get("tts_voice", "冰糖") or "冰糖"),
        gemini_api_key=_env("GEMINI_API_KEY", str(gemini.get("api_key", "") or "")),
        gemini_model=str(gemini.get("model", "gemini-2.0-flash-live-001") or "gemini-2.0-flash-live-001"),
        gemini_voice=str(gemini.get("voice", "Puck") or "Puck"),
        openai_api_key=_env("OPENAI_API_KEY", str(openai.get("api_key", "") or "")),
        openai_realtime_model=str(
            openai.get("realtime_model", "gpt-4o-mini-realtime-preview") or "gpt-4o-mini-realtime-preview"
        ),
        memory_path=str(_get(agent_raw, "memory_path", "data/voice_memory.jsonl") or "data/voice_memory.jsonl"),
        memory_max_turns=int(_get(agent_raw, "memory_max_turns", 30)),
    )

    api = VoiceApiSettings(
        enabled=bool(_get(api_raw, "enabled", False)),
        host=str(_get(api_raw, "host", "127.0.0.1") or "127.0.0.1"),
        port=int(_get(api_raw, "port", 3091)),
        token=_env("VOICE_API_TOKEN", str(api_raw.get("token", "") or "")),
    )
    return agent, api
