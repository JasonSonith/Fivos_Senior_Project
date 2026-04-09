import importlib
import os


def test_ollama_url_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)
    assert llm_extractor.OLLAMA_URL == "http://localhost:11434/api/chat"


def test_ollama_url_respects_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/api/chat")
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)
    assert llm_extractor.OLLAMA_URL == "http://ollama:11434/api/chat"
