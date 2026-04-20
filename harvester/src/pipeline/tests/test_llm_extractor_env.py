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


def test_model_chain_is_cloud_first_with_small_local_fallback():
    """Portable Docker: chain runs on any laptop without GPU."""
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)

    chain = llm_extractor.MODEL_CHAIN
    assert len(chain) == 6, f"Expected 6 models, got {len(chain)}"

    # Cloud providers must come first
    assert chain[0] == {"provider": "groq", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"}
    assert chain[1] == {"provider": "groq", "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY"}
    assert chain[2]["provider"] == "nvidia"
    assert chain[3]["provider"] == "nvidia"
    assert chain[4]["provider"] == "nvidia"

    # Single small local model as last resort
    assert chain[5] == {"provider": "ollama", "model": "qwen2.5:3b"}

    # Removed models must not appear
    model_names = [m["model"] for m in chain]
    assert "gemma4" not in model_names
    assert "qwen2.5:7b" not in model_names
    assert "mistral" not in model_names
