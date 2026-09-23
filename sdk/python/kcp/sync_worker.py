"""
KCP Adaptive Sync Worker

Background daemon thread that delivers queued artifacts to peers.
Implements adaptive batching, exponential backoff retry, and circuit breaker.

RFC KCP-003 — Phase 1 implementation.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .store import LocalStore

logger = logging.getLogger("kcp.sync")


# ─── Adaptive batch sizing ─────────────────────────────────────
#
# queue_depth  →  (batch_size, interval_seconds)
#
_BATCH_POLICY = [
    (10, 1, 5),  # ≤10 pending   → batch=1,  every 5s  (feels instant)
    (100, 10, 30),  # ≤100 pending  → batch=10, every 30s
    (1000, 50, 60),  # ≤1000 pending → batch=50, every 60s
]
_DEFAULT_BATCH = (100, 120)  # >1000 pending → batch=100, every 120s


def _adaptive_params(queue_depth: int) -> tuple[int, int]:
    """Return (batch_size, sleep_seconds) based on current queue depth."""
    for max_depth, batch, interval in _BATCH_POLICY:
        if queue_depth <= max_depth:
            return batch, interval
    return _DEFAULT_BATCH


# ─── Circuit Breaker ────────────────────────────────────────────


class CircuitBreaker:
    """
    Per-peer circuit breaker.

    States:
      CLOSED     → normal operation
      OPEN       → peer considered down, no requests sent
      HALF_OPEN  → probe request sent, waiting for result
    """

    _DEFAULT_FAILURE_THRESHOLD = 3
    _DEFAULT_RECOVERY_TIMEOUT = 300

    def __init__(self, peer_url: str):
        self.peer_url = peer_url
        self._failures = 0
        self._state = "CLOSED"
        self._opened_at: float = 0.0
        self._lock = threading.Lock()
        # Instance-level thresholds so tests can override easily
        self.failure_threshold: int = self._DEFAULT_FAILURE_THRESHOLD
        self.recovery_timeout: int = self._DEFAULT_RECOVERY_TIMEOUT

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state == "OPEN":
                if time.time() - self._opened_at >= self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    logger.info(f"Circuit HALF_OPEN for {self.peer_url}")
                    return False
                return True
            return False

    def record_success(self):
        with self._lock:
            self._failures = 0
            if self._state != "CLOSED":
                logger.info(f"Circuit CLOSED (recovered) for {self.peer_url}")
            self._state = "CLOSED"

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._state == "CLOSED":
                self._state = "OPEN"
                self._opened_at = time.time()
                logger.warning(f"Circuit OPEN for {self.peer_url} after {self._failures} consecutive failures")

    @property
    def state(self) -> str:
        return self._state


# ─── Sync Worker ────────────────────────────────────────────────


class SyncWorker:
    """
    Background daemon thread — adaptive async sync engine.

    Lifecycle:
      - Created and started by KCPNode on first public publish
      - Runs until node.close() is called
      - Daemon=True: exits automatically when main process exits

    Features:
      - Adaptive batch sizing based on queue depth
      - Exponential backoff retry (30s → 24h)
      - Circuit breaker per peer (3 failures → OPEN → 5min cooldown)
      - Delivery confirmation: only marks done after peer ACK
      - Persistent queue: survives process restarts
    """

    def __init__(self, store: LocalStore, peer_urls: list[str]):
        self.store = store
        self.peer_urls = peer_urls
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="kcp-sync-worker",
            daemon=True,
        )
        self._circuits: dict[str, CircuitBreaker] = {url: CircuitBreaker(url) for url in peer_urls}
        self._session = requests.Session()
        self._session.headers.update({"X-KCP-Client": "kcp-python/0.2.0"})

    def start(self):
        """Start the background sync thread."""
        if not self._thread.is_alive():
            self._thread.start()
            logger.info(f"SyncWorker started — peers: {self.peer_urls}")

    def stop(self, timeout: float = 5.0):
        """Signal the worker to stop and wait for it."""
        self._stop.set()
        self._thread.join(timeout=timeout)

    def add_peer(self, peer_url: str):
        """Dynamically add a new peer (thread-safe)."""
        if peer_url not in self._circuits:
            self._circuits[peer_url] = CircuitBreaker(peer_url)
        if peer_url not in self.peer_urls:
            self.peer_urls.append(peer_url)

    def status(self) -> dict:
        """Return current worker status including circuit states."""
        queue_stats = self.store.sync_queue_stats()
        return {
            "running": self._thread.is_alive(),
            "peers": {
                url: {
                    "circuit": self._circuits[url].state,
                    **queue_stats.get(url, {"pending": 0, "done": 0, "failed": 0}),
                }
                for url in self.peer_urls
            },
        }

    # ─── Internal ──────────────────────────────────────────────

    def _run(self):
        """Main sync loop."""
        logger.info("SyncWorker loop started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"SyncWorker tick error: {e}", exc_info=True)

    def _tick(self):
        """One sync cycle: fetch pending items, push, sleep."""
        # Estimate queue depth to pick batch params
        queue_depth = sum(v.get("pending", 0) for v in self.store.sync_queue_stats().values())
        batch_size, sleep_secs = _adaptive_params(queue_depth)

        items = self.store.dequeue_pending_sync(batch_size)

        for item in items:
            if self._stop.is_set():
                break
            peer_url = item["peer_url"]
            circuit = self._circuits.get(peer_url)
            if circuit and circuit.is_open:
                # Re-enqueue: reset to pending so retry happens when circuit recovers
                self.store.nack_sync(item["id"], "circuit open", max_attempts=99)
                continue
            self._push_one(item)

        # Wait before next tick — but wake up early if stop requested
        self._stop.wait(timeout=sleep_secs)

    def _push_one(self, item: dict):
        """Push a single artifact to a peer and handle ACK/NACK."""
        artifact_id = item["artifact_id"]
        peer_url = item["peer_url"]
        queue_id = item["id"]
        circuit = self._circuits.get(peer_url)

        try:
            # Fetch artifact payload
            payload = self.store.get_artifact_with_content(artifact_id)
            if not payload:
                # Artifact deleted — remove from queue silently
                self.store.ack_sync(queue_id)
                return

            resp = self._session.post(
                f"{peer_url.rstrip('/')}/kcp/v1/sync/push",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()

            # Peer returned accepted=True or accepted=False (duplicate/invalid)
            # Both count as delivery — no retry needed
            self.store.ack_sync(queue_id)

            # Record replication ACK (peer confirmed receipt)
            self.store.record_replication_ack(artifact_id, peer_url)

            if circuit:
                circuit.record_success()

            accepted = result.get("accepted", True)
            logger.debug(f"Synced {artifact_id[:8]}… → {peer_url} [accepted={accepted}]")

        except requests.exceptions.ConnectionError as e:
            self._handle_failure(queue_id, circuit, f"connection error: {e}")
        except requests.exceptions.Timeout as e:
            self._handle_failure(queue_id, circuit, f"timeout: {e}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status == 409:
                # Conflict = already exists → ACK, no retry
                self.store.ack_sync(queue_id)
            else:
                self._handle_failure(queue_id, circuit, f"HTTP {status}: {e}")
        except Exception as e:
            self._handle_failure(queue_id, circuit, str(e))

    def _handle_failure(self, queue_id: int, circuit: CircuitBreaker | None, error: str):
        """Record failure, update circuit breaker, schedule retry."""
        logger.warning(f"Sync failure (queue_id={queue_id}): {error}")
        self.store.nack_sync(queue_id, error)
        if circuit:
            circuit.record_failure()
