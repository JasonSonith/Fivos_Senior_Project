"""Concurrency and thread-safety tests for llm_extractor."""
import threading
from unittest.mock import patch

from pipeline import llm_extractor
from pipeline.llm_extractor import _set_last_model, get_last_model


def test_thread_local_last_model():
    """Each thread's get_last_model() returns its own thread's value, not another's."""
    results = {}
    barrier = threading.Barrier(2)

    def worker(name: str, model: str):
        _set_last_model(model)
        barrier.wait()  # ensure both threads have set before either reads
        results[name] = get_last_model()

    t1 = threading.Thread(target=worker, args=("A", "gemma4"))
    t2 = threading.Thread(target=worker, args=("B", "llama-3.3-70b-versatile"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["A"] == "gemma4"
    assert results["B"] == "llama-3.3-70b-versatile"


def test_non_blocking_sem_falls_through_when_saturated():
    """When Ollama semaphore is saturated, _llm_request skips to the next model."""
    # Pre-acquire the Ollama slot so the first model in the chain can't be used
    llm_extractor._provider_sems["ollama"].acquire()
    try:
        # Mock Groq env key so the chain will try it
        with patch.dict("os.environ", {"GROQ_API_KEY": "fake-key"}):
            # Mock _openai_request to return a canned response for Groq
            with patch.object(llm_extractor, "_openai_request") as mock_openai:
                mock_openai.return_value = {"device_name": "FALLBACK"}
                result = llm_extractor._llm_request(
                    system_msg="sys",
                    user_msg="user",
                    schema={},
                    timeout=5,
                )
        assert result == {"device_name": "FALLBACK"}
        # The last-model should be a Groq model (not gemma4)
        assert "groq" not in (get_last_model() or "").lower() or get_last_model() != "gemma4"
        assert get_last_model() != "gemma4"
    finally:
        llm_extractor._provider_sems["ollama"].release()


def test_disabled_models_respected_across_threads():
    """A model disabled by one thread stays disabled for another."""
    # Reset state
    with llm_extractor._disabled_lock:
        llm_extractor._disabled_models.clear()
    llm_extractor._disable_model("gemma4")

    seen_models = []
    lock = threading.Lock()

    def fake_openai_request(url, api_key, model, messages, timeout, _retry=False):
        with lock:
            seen_models.append(model)
        return {"device_name": "OK"}

    with patch.dict("os.environ", {"GROQ_API_KEY": "k", "NVIDIA_API_KEY": "k"}):
        with patch.object(llm_extractor, "_openai_request", side_effect=fake_openai_request):
            threads = [
                threading.Thread(
                    target=llm_extractor._llm_request,
                    args=("sys", "user", {}, 5),
                )
                for _ in range(4)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

    # None of the threads should have tried gemma4 (it's disabled)
    assert "gemma4" not in seen_models

    # Cleanup
    with llm_extractor._disabled_lock:
        llm_extractor._disabled_models.clear()
