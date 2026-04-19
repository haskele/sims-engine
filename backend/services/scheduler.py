"""Intraday data refresh scheduler.

Uses pure asyncio (no external dependencies) to run periodic data refresh
jobs during game hours. Each job is independently scheduled, fault-isolated,
and exposes status for the admin endpoint.

Configuration is loaded from config/scheduler_config.json but can be
overridden by environment variables prefixed with DFS_SCHED_.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "scheduler_config.json"


# ---------------------------------------------------------------------------
# Timezone helper
# ---------------------------------------------------------------------------


def _get_et() -> Any:
    """Return Eastern Time timezone object."""
    if ZoneInfo:
        return ZoneInfo("America/New_York")
    return timezone(timedelta(hours=-4))


def _now_et() -> datetime:
    """Current time in Eastern."""
    return datetime.now(_get_et())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _load_config() -> Dict[str, Any]:
    """Load scheduler config from JSON, with env var overrides."""
    config: Dict[str, Any] = {}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
        except Exception as exc:
            logger.warning("Failed to load scheduler config: %s", exc)

    # Env var overrides (e.g. DFS_SCHED_REFRESH_LINEUPS_INTERVAL=3)
    for key, val in os.environ.items():
        if key.startswith("DFS_SCHED_"):
            parts = key[len("DFS_SCHED_"):].lower().split("_")
            # e.g. DFS_SCHED_REFRESH_LINEUPS_INTERVAL -> jobs.refresh_lineups.interval_minutes
            if len(parts) >= 3 and parts[-1] == "interval":
                job_name = "_".join(parts[:-1])
                jobs = config.setdefault("jobs", {})
                job_cfg = jobs.setdefault(job_name, {})
                try:
                    job_cfg["interval_minutes"] = int(val)
                except ValueError:
                    pass
            elif len(parts) >= 3 and parts[-1] == "enabled":
                job_name = "_".join(parts[:-1])
                jobs = config.setdefault("jobs", {})
                job_cfg = jobs.setdefault(job_name, {})
                job_cfg["enabled"] = val.lower() in ("1", "true", "yes")

    return config


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------


@dataclass
class ScheduledJob:
    """A single scheduled refresh job."""

    name: str
    func: Callable[[], Coroutine[Any, Any, Any]]
    interval_minutes: float = 10.0
    enabled: bool = True
    game_hours_only: bool = True
    description: str = ""

    # Runtime state
    last_run: Optional[float] = field(default=None, repr=False)
    last_duration: Optional[float] = field(default=None, repr=False)
    last_error: Optional[str] = field(default=None, repr=False)
    run_count: int = field(default=0, repr=False)
    error_count: int = field(default=0, repr=False)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    @property
    def next_run(self) -> Optional[float]:
        """Estimate next run time as unix timestamp."""
        if self.last_run is None:
            return None
        return self.last_run + (self.interval_minutes * 60)

    def status_dict(self) -> Dict[str, Any]:
        """Return status info for the admin endpoint."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "interval_minutes": self.interval_minutes,
            "game_hours_only": self.game_hours_only,
            "description": self.description,
            "last_run": datetime.fromtimestamp(self.last_run, tz=_get_et()).isoformat() if self.last_run else None,
            "last_duration_seconds": round(self.last_duration, 2) if self.last_duration else None,
            "last_error": self.last_error,
            "next_run": datetime.fromtimestamp(self.next_run, tz=_get_et()).isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
        }


# ---------------------------------------------------------------------------
# Game hours check
# ---------------------------------------------------------------------------


def _is_game_hours(config: Dict[str, Any]) -> bool:
    """Check if current ET time falls within the configured game hours window.

    Handles the overnight wrap (e.g. 10 AM to 1 AM next day).
    """
    gh = config.get("game_hours", {})
    start_hour = gh.get("start_hour", 10)
    start_minute = gh.get("start_minute", 0)
    end_hour = gh.get("end_hour", 1)
    end_minute = gh.get("end_minute", 0)

    now = _now_et()
    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute

    # Handle overnight wrap: if end < start, the window spans midnight
    if end_minutes <= start_minutes:
        # Active if after start OR before end
        return current_minutes >= start_minutes or current_minutes < end_minutes
    else:
        # Simple window within same day
        return start_minutes <= current_minutes < end_minutes


# ---------------------------------------------------------------------------
# Job implementations
# ---------------------------------------------------------------------------


async def _refresh_lineups() -> None:
    """Fetch latest lineup confirmations from external sources."""
    from services.lineup_scraper import fetch_lineups
    games = await fetch_lineups(force_refresh=True)
    logger.info("refresh_lineups: fetched %d games with lineup data", len(games))


async def _refresh_odds() -> None:
    """Fetch latest odds. Respects prematch lock in vegas.py.

    The prematch lock in fetch_fantasylabs_odds() means once odds are locked
    for a date, this call returns the cached locked values (no-op effectively).
    We still call it so that if odds haven't been locked yet (no totals posted),
    a fresh fetch may succeed and lock them.
    """
    from services.vegas import fetch_fantasylabs_odds
    today_str = _now_et().date().isoformat()
    odds = await fetch_fantasylabs_odds(target_date=today_str)
    logger.info("refresh_odds: fetched %d game odds for %s", len(odds), today_str)


async def _refresh_projections() -> None:
    """Re-run the projection pipeline with latest lineups/odds."""
    from services.projection_pipeline import generate_projections
    from api.staging_projections import _projection_cache

    today_str = _now_et().date().isoformat()
    cache_key = f"{today_str}-dk"

    projections = await generate_projections(
        target_date=today_str, site="dk", n_sims=1000,
    )

    if projections:
        _projection_cache[cache_key] = (time.time(), projections)
        logger.info(
            "refresh_projections: generated %d projections for %s",
            len(projections), today_str,
        )
    else:
        logger.warning("refresh_projections: pipeline returned 0 projections")


async def _refresh_slates() -> None:
    """Fetch DK lobby for new/updated slates."""
    from services.slate_manager import fetch_dk_slates
    slates = await fetch_dk_slates()
    logger.info("refresh_slates: found %d DK slates", len(slates))


async def _nightly_generation() -> None:
    """Generate next-day projections (the 8 PM ET nightly job)."""
    from services.projection_pipeline import generate_projections
    from api.staging_projections import _projection_cache

    tomorrow = (_now_et() + timedelta(days=1)).date()
    date_str = tomorrow.isoformat()

    projections = await generate_projections(
        target_date=date_str, site="dk", n_sims=1000,
    )

    if projections:
        cache_key = f"{date_str}-dk"
        _projection_cache[cache_key] = (time.time(), projections)
        logger.info(
            "nightly_generation: generated %d projections for %s",
            len(projections), date_str,
        )
    else:
        logger.warning("nightly_generation: pipeline returned 0 projections for %s", date_str)


# ---------------------------------------------------------------------------
# Scheduler class
# ---------------------------------------------------------------------------


class Scheduler:
    """Manages all scheduled refresh jobs using asyncio tasks."""

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def setup(self) -> None:
        """Load config and register all jobs."""
        self.config = _load_config()
        jobs_config = self.config.get("jobs", {})

        # Register each job
        job_definitions = [
            ("refresh_lineups", _refresh_lineups, True),
            ("refresh_odds", _refresh_odds, True),
            ("refresh_projections", _refresh_projections, True),
            ("refresh_slates", _refresh_slates, False),  # slates run regardless of game hours
            ("nightly_generation", _nightly_generation, False),  # nightly has its own schedule
        ]

        for name, func, game_hours_only in job_definitions:
            job_cfg = jobs_config.get(name, {})
            self.jobs[name] = ScheduledJob(
                name=name,
                func=func,
                interval_minutes=job_cfg.get("interval_minutes", 10),
                enabled=job_cfg.get("enabled", True),
                game_hours_only=game_hours_only,
                description=job_cfg.get("description", ""),
            )

        logger.info(
            "Scheduler configured with %d jobs: %s",
            len(self.jobs),
            ", ".join(f"{j.name}({'on' if j.enabled else 'off'})" for j in self.jobs.values()),
        )

    async def start(self) -> None:
        """Start all enabled job loops."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self.setup()

        for job in self.jobs.values():
            if job.enabled:
                task = asyncio.create_task(self._job_loop(job))
                self._tasks.append(task)
                job._task = task

        logger.info("Scheduler started with %d active job loops", len(self._tasks))

    async def stop(self) -> None:
        """Cancel all job loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def trigger_job(self, job_name: str) -> Dict[str, Any]:
        """Manually trigger a job immediately. Returns result info."""
        job = self.jobs.get(job_name)
        if not job:
            return {"error": f"Unknown job: {job_name}"}

        return await self._execute_job(job)

    def get_status(self) -> Dict[str, Any]:
        """Return status of all jobs."""
        now = _now_et()
        return {
            "running": self._running,
            "current_time_et": now.isoformat(),
            "is_game_hours": _is_game_hours(self.config),
            "game_hours_config": self.config.get("game_hours", {}),
            "jobs": {name: job.status_dict() for name, job in self.jobs.items()},
        }

    def set_job_enabled(self, job_name: str, enabled: bool) -> bool:
        """Enable or disable a job. Returns True if job exists."""
        job = self.jobs.get(job_name)
        if not job:
            return False
        job.enabled = enabled
        logger.info("Job '%s' %s", job_name, "enabled" if enabled else "disabled")
        return True

    # ── Internal ──────────────────────────────────────────────────────────

    async def _job_loop(self, job: ScheduledJob) -> None:
        """Main loop for a single job. Runs forever until cancelled."""
        # Special handling for nightly_generation: waits for the specific time
        if job.name == "nightly_generation":
            await self._nightly_loop(job)
            return

        # Standard interval-based jobs
        # Initial delay: stagger jobs slightly to avoid thundering herd
        stagger = hash(job.name) % 30
        await asyncio.sleep(stagger)

        while self._running:
            try:
                if not job.enabled:
                    await asyncio.sleep(60)
                    continue

                # Check game hours constraint
                if job.game_hours_only and not _is_game_hours(self.config):
                    # Outside game hours: sleep 5 minutes and recheck
                    await asyncio.sleep(300)
                    continue

                # Execute the job
                await self._execute_job(job)

                # Sleep until next interval
                await asyncio.sleep(job.interval_minutes * 60)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                # This should never happen since _execute_job catches everything,
                # but belt-and-suspenders
                logger.error("Unexpected error in job loop '%s': %s", job.name, exc)
                await asyncio.sleep(60)

    async def _nightly_loop(self, job: ScheduledJob) -> None:
        """Loop for the nightly generation job. Waits for the configured time."""
        jobs_config = self.config.get("jobs", {})
        nightly_cfg = jobs_config.get("nightly_generation", {})
        run_hour = nightly_cfg.get("run_hour", 20)
        run_minute = nightly_cfg.get("run_minute", 0)

        while self._running:
            try:
                if not job.enabled:
                    await asyncio.sleep(60)
                    continue

                now = _now_et()
                target = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                logger.info(
                    "nightly_generation: next run at %s ET (%.0f min from now)",
                    target.strftime("%Y-%m-%d %H:%M"), wait_seconds / 60,
                )
                await asyncio.sleep(wait_seconds)

                # Execute
                await self._execute_job(job)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Nightly loop error: %s", exc)
                await asyncio.sleep(300)

    async def _execute_job(self, job: ScheduledJob) -> Dict[str, Any]:
        """Execute a single job with timing, logging, and error handling."""
        logger.info("Job '%s' starting", job.name)
        t0 = time.time()

        try:
            await job.func()
            elapsed = time.time() - t0
            job.last_run = time.time()
            job.last_duration = elapsed
            job.last_error = None
            job.run_count += 1
            logger.info("Job '%s' completed in %.1fs", job.name, elapsed)
            return {
                "job": job.name,
                "status": "success",
                "duration_seconds": round(elapsed, 2),
            }
        except Exception as exc:
            elapsed = time.time() - t0
            job.last_run = time.time()
            job.last_duration = elapsed
            job.last_error = str(exc)
            job.run_count += 1
            job.error_count += 1
            logger.error(
                "Job '%s' failed after %.1fs: %s", job.name, elapsed, exc, exc_info=True,
            )
            return {
                "job": job.name,
                "status": "error",
                "error": str(exc),
                "duration_seconds": round(elapsed, 2),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

scheduler = Scheduler()
