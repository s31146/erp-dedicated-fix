"""Month-end simulation: the whale's finance team runs reports concurrently.

Workers call the API over HTTP, like real users would. Stop is cooperative:
the status endpoint reports STOPPED as soon as the stop signal is set, even
while an in-flight HTTP request is finishing.
"""
import os
import threading

import httpx

API_URL = os.getenv("SIM_API_URL", "http://127.0.0.1:8000")
WORKERS = int(os.getenv("SIM_WHALE_WORKERS", "40"))

_stop = threading.Event()
_threads: list[threading.Thread] = []
_lock = threading.Lock()


def _worker() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        while not _stop.is_set():
            try:
                client.get("/t/1/reports/monthly", params={"year": 2026})
            except httpx.HTTPError:
                _stop.wait(0.5)


def running() -> bool:
    # Do not show RUNNING after Stop was requested just because an HTTP call
    # is still unwinding in a worker thread.
    return not _stop.is_set() and any(t.is_alive() for t in _threads)


def start() -> None:
    with _lock:
        if running():
            return
        _stop.clear()
        _threads.clear()
        for _ in range(WORKERS):
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            _threads.append(t)


def stop() -> None:
    _stop.set()
