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


def test_model_chain_is_local_first_capability_ordered():
    """gemma4:e4b is primary; cloud models follow in capability order."""
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)

    chain = llm_extractor.MODEL_CHAIN
    assert len(chain) == 5, f"Expected 5 models, got {len(chain)}"

    # gemma4:e4b is primary (local, most capable per user judgment)
    assert chain[0] == {"provider": "ollama", "model": "gemma4:e4b"}

    # Cloud fallback ordered by raw capability
    assert chain[1] == {"provider": "nvidia", "model": "mistralai/mistral-large", "env_key": "NVIDIA_API_KEY"}
    assert chain[2] == {"provider": "groq", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"}
    assert chain[3] == {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"}
    assert chain[4] == {"provider": "groq", "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY"}

    # Removed models must not appear
    model_names = [m["model"] for m in chain]
    assert "qwen2.5:3b" not in model_names
    assert "qwen2.5:7b" not in model_names
    assert "google/gemma-2-27b-it" not in model_names
