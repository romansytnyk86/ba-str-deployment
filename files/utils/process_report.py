"""
utils/process_report.py - Structured workflow report logging.

Creates one JSON report file per command run with:
- command metadata
- selected/skipped steps
- per-step status and duration
- final result
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Optional

logger = logging.getLogger("sgb2_freigabe")


@dataclass
class StepRecord:
    step_id: int
    name: str
    started_at: str
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "running"
    details: str = ""


@dataclass
class ProcessReport:
    command: str
    log_dir: Path
    only_steps: list[int] = field(default_factory=list)
    skip_steps: list[int] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    success: Optional[bool] = None
    steps: list[StepRecord] = field(default_factory=list)
    _step_timers: dict[int, float] = field(default_factory=dict)

    def start_step(self, step_id: int, name: str) -> None:
        self._step_timers[step_id] = perf_counter()
        self.steps.append(
            StepRecord(step_id=step_id, name=name, started_at=datetime.now().isoformat())
        )

    def finish_step(self, step_id: int, success: bool, details: str = "") -> None:
        record = next((s for s in reversed(self.steps) if s.step_id == step_id and s.status == "running"), None)
        if record is None:
            return
        record.finished_at = datetime.now().isoformat()
        start = self._step_timers.pop(step_id, None)
        record.duration_seconds = round(perf_counter() - start, 3) if start is not None else None
        record.status = "success" if success else "failed"
        record.details = details

    def skip_step(self, step_id: int, name: str, reason: str) -> None:
        now = datetime.now().isoformat()
        self.steps.append(
            StepRecord(
                step_id=step_id,
                name=name,
                started_at=now,
                finished_at=now,
                duration_seconds=0.0,
                status="skipped",
                details=reason,
            )
        )

    def finalize(self, success: bool) -> Path:
        self.success = success
        self.finished_at = datetime.now().isoformat()

        reports_dir = self.log_dir / "process_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = reports_dir / f"{timestamp}_{self.command}.json"

        payload = {
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success": self.success,
            "only_steps": self.only_steps,
            "skip_steps": self.skip_steps,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "duration_seconds": s.duration_seconds,
                    "details": s.details,
                }
                for s in self.steps
            ],
        }

        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        logger.info(f"Process report: {report_path.absolute()}")
        return report_path
