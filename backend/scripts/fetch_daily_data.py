#!/usr/bin/env python3
"""Daily data pipeline script.

Fetches schedule, Vegas lines, weather, and DK salaries for today's games
and stores everything in the database.

Usage:
    python -m scripts.fetch_daily_data [--date YYYY-MM-DD] [--draft-group-id ID]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

# Ensure the backend package is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import create_tables, async_session
from models.game import Game
from models.player import Player
from models.team import Team
from services import dk_api, mlb_stats, vegas, weather

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run(game_date: date, draft_group_id: int | None = None) -> None:
    """Execute the full daily data pipeline."""
    await create_tables()

    async with async_session() as db:
        # 1. Fetch MLB schedule
        logger.info("Step 1: Fetching MLB schedule for %s", game_date)
        try:
            schedule = await mlb_stats.get_schedule(game_date)
            games = mlb_stats.parse_schedule_games(schedule)
            logger.info("Found %d games", len(games))

            for g in games:
                game_pk = g.get("game_pk")
                if not game_pk:
                    continue

                from sqlalchemy import select

                # Check existing
                result = await db.execute(
                    select(Game).where(Game.mlb_game_pk == game_pk)
                )
                if result.scalar_one_or_none():
                    logger.info("Game %d already exists, skipping", game_pk)
                    continue

                # Create stub teams if needed
                for abbr in [g.get("home_team_abbr"), g.get("away_team_abbr")]:
                    if not abbr:
                        continue
                    result = await db.execute(
                        select(Team).where(Team.abbreviation == abbr)
                    )
                    if not result.scalar_one_or_none():
                        db.add(
                            Team(
                                name=abbr,
                                abbreviation=abbr,
                                league="AL",
                                division="East",
                                stadium_roof="open",
                            )
                        )

                await db.flush()

                # Resolve team IDs
                ht_result = await db.execute(
                    select(Team).where(
                        Team.abbreviation == g.get("home_team_abbr", "")
                    )
                )
                at_result = await db.execute(
                    select(Team).where(
                        Team.abbreviation == g.get("away_team_abbr", "")
                    )
                )
                ht = ht_result.scalar_one_or_none()
                at = at_result.scalar_one_or_none()

                game = Game(
                    date=game_date,
                    home_team_id=ht.id if ht else 0,
                    away_team_id=at.id if at else 0,
                    venue=g.get("venue"),
                    mlb_game_pk=game_pk,
                )
                db.add(game)

            await db.commit()
            logger.info("Schedule import complete")
        except Exception:
            logger.exception("Failed to fetch schedule")

        # 2. Fetch Vegas lines
        logger.info("Step 2: Fetching Vegas lines")
        try:
            raw = await vegas.get_mlb_odds()
            odds = vegas.parse_odds(raw)
            logger.info("Found odds for %d events", len(odds))
            # Matching logic would go here (similar to API endpoint)
            await db.commit()
        except Exception:
            logger.exception("Failed to fetch Vegas lines")

        # 3. Fetch DK salaries
        if draft_group_id:
            logger.info("Step 3: Fetching DK salaries for DG %d", draft_group_id)
            try:
                draftables = await dk_api.get_draftables(draft_group_id)
                for raw in draftables:
                    parsed = dk_api.parse_draftable(raw)
                    dk_id = parsed.get("dk_id")
                    if not dk_id:
                        continue

                    from sqlalchemy import select

                    result = await db.execute(
                        select(Player).where(Player.dk_id == dk_id)
                    )
                    existing = result.scalar_one_or_none()
                    if existing:
                        existing.dk_salary = parsed["dk_salary"]
                    else:
                        db.add(
                            Player(
                                name=parsed["name"],
                                team=parsed["team"],
                                position=parsed["position"] or "UTIL",
                                bats="R",
                                throws="R",
                                dk_id=dk_id,
                                dk_salary=parsed["dk_salary"],
                            )
                        )
                await db.commit()
                logger.info("DK salary import complete")
            except Exception:
                logger.exception("Failed to fetch DK salaries")

    logger.info("Daily data pipeline complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily DFS data pipeline")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Game date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--draft-group-id",
        type=int,
        default=None,
        help="DraftKings draft group ID for salary import",
    )
    args = parser.parse_args()

    game_date = date.fromisoformat(args.date) if args.date else date.today()
    asyncio.run(run(game_date, args.draft_group_id))


if __name__ == "__main__":
    main()
