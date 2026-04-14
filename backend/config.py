"""Application configuration."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Baseball DFS Simulator"
    debug: bool = True

    # Database — uses /app/data on Fly.io (mounted volume), ../data locally
    database_url: str = f"sqlite+aiosqlite:///{Path('/app/data/dfs.db') if Path('/app/data').exists() else Path(__file__).resolve().parent.parent / 'data' / 'dfs.db'}"

    # DraftKings endpoints
    dk_contests_url: str = "https://www.draftkings.com/lobby/getcontests?sport=MLB"
    dk_draftgroups_url: str = "https://api.draftkings.com/draftgroups/v1/"
    dk_salaries_csv_url: str = "https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={draft_group_id}"
    dk_draftables_url: str = "https://api.draftkings.com/draftgroups/v1/draftgroups/{draft_group_id}/draftables"
    dk_sportsbook_url: str = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/84240"

    # MLB Stats API
    mlb_schedule_url: str = "https://statsapi.mlb.com/api/v1/schedule"
    mlb_people_url: str = "https://statsapi.mlb.com/api/v1/people"

    # Weather
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"

    # Salary caps
    dk_salary_cap: int = 50000
    fd_salary_cap: int = 35000

    # Default sim settings
    default_sim_count: int = 10000

    model_config = {"env_prefix": "DFS_"}


settings = Settings()


# ── DraftKings Classic MLB Scoring ──────────────────────────────────────────

DK_HITTER_SCORING = {
    "single": 3,
    "double": 5,
    "triple": 8,
    "homeRun": 10,
    "rbi": 2,
    "run": 2,
    "baseOnBalls": 2,
    "hitByPitch": 2,
    "stolenBase": 5,
}

DK_PITCHER_SCORING = {
    "win": 4,
    "earnedRun": -2,
    "strikeOut": 2,
    "inningsPitched": 2.25,
    "hitAllowed": -0.6,
    "baseOnBallsAllowed": -0.6,
    "hitByPitchAllowed": -0.6,
    "completeGame": 2.5,
    "completeGameShutout": 2.5,
    "noHitter": 5,
}

# ── FanDuel Classic MLB Scoring ─────────────────────────────────────────────

FD_HITTER_SCORING = {
    "single": 3,
    "double": 6,
    "triple": 9,
    "homeRun": 12,
    "rbi": 3.5,
    "run": 3.2,
    "baseOnBalls": 3,
    "stolenBase": 6,
    "hitByPitch": 3,
}

FD_PITCHER_SCORING = {
    "win": 6,
    "qualityStart": 4,
    "earnedRun": -3,
    "strikeOut": 3,
    "inningsPitched": 3,
}

# ── Roster formats ──────────────────────────────────────────────────────────

DK_ROSTER_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
FD_ROSTER_SLOTS = ["P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]
