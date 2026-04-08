"""Concurrency and thread-safety tests for llm_extractor."""
import threading

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
