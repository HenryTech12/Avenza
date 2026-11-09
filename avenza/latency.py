"""Per-stage latency records for the measured-results report.

Every voice turn produces one JSON line with the time spent in each stage,
so the team can report measured numbers (median and slow cases) instead of
vendor claims. ``scripts/latency_report.py`` summarises the file.

Stages (milliseconds, missing when the stage did not run):

* ``vad_ms``          client: the VAD silence tolerance that ended the turn
* ``stt_ttfp_ms``     provider: first partial transcript after first audio
* ``stt_final_ms``    provider: final transcript after end of speech
* ``stt_wait_ms``     server: end of speech until the transcript was ready
* ``intent_ms``       intent classification
* ``name_enquiry_ms`` bank name check
* ``tts_ttfa_ms``     provider: first audio of the spoken reply
* ``reply_ms``        server: end of speech until the reply was sent
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from .timeutil import iso, utcnow

logger = logging.getLogger("avenza.latency")


class Turn:
    """Timings for one customer turn."""

    def __init__(self, session_id: str, provider: str = ""):
        self.session_id = session_id
        self.started = time.perf_counter()
        self.stages: dict[str, int] = {}
        self.meta: dict[str, object] = {"provider": provider}
        self.external_wait_ms = 0

    def mark(self, stage: str, ms: float | int | None) -> None:
        if ms is None:
            return
        self.stages[stage] = int(ms)

    def since_start_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def record(self) -> dict:
        return {
            "ts": iso(utcnow()),
            "session_id": self.session_id,
            **{k: v for k, v in self.meta.items() if v not in (None, "")},
            **self.stages,
        }


class LatencyLog:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def write(self, turn: Turn) -> dict:
        record = turn.record()
        logger.info("latency %s", json.dumps(record, sort_keys=True))
        if self.path is None:
            return record
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            logger.warning("could not write latency log to %s", self.path)
        return record
