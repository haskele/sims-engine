#!/usr/bin/env python3
"""Historical contest and lineup scraper (DraftKings).

This script scrapes completed contest results from DraftKings to build a
historical lineup corpus for the lineup_sampler module.

NOTE: Requires DraftKings authentication (session cookies). These must be
exported from a browser session and stored in a cookies file.

Usage:
    python -m scripts.scrape_contest_results --contest-id 12345 --cookies ~/dk_cookies.json

The scraper will:
1. Fetch the contest leaderboard (all entries with finish positions)
2. For each entry, fetch the lineup details (player picks + salaries)
3. Store everything in the lineups table with the contest reference

This data is then used by services/lineup_sampler.py to learn construction
patterns and build realistic opponent fields for simulation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# DraftKings contest results endpoints (require auth cookies)
DK_CONTEST_LEADERBOARD_URL = (
    "https://www.draftkings.com/contest/gamecenter/{contest_id}"
)
DK_CONTEST_ENTRIES_URL = (
    "https://api.draftkings.com/contests/v1/contests/{contest_id}/entries"
)
DK_ENTRY_LINEUP_URL = (
    "https://api.draftkings.com/lineups/v1/entries/{entry_id}"
)


async def scrape_contest(
    contest_id: str,
    cookies_path: str,
    max_entries: int = 5000,
) -> None:
    """Scrape a completed DraftKings contest.

    Parameters
    ----------
    contest_id : str
        The DK contest ID.
    cookies_path : str
        Path to a JSON file with DK session cookies.
    max_entries : int
        Maximum number of entries to scrape.
    """
    import httpx

    from database import create_tables, async_session
    from models.contest import Contest
    from models.lineup import Lineup

    # Load cookies
    cookies_file = Path(cookies_path).expanduser()
    if not cookies_file.exists():
        logger.error("Cookies file not found: %s", cookies_file)
        logger.info(
            "To get cookies: log into DraftKings in your browser, then export "
            "cookies as JSON using a browser extension (e.g., EditThisCookie)."
        )
        return

    with open(cookies_file) as f:
        cookies_data = json.load(f)

    # Convert to httpx-compatible cookies
    cookies = {}
    for c in cookies_data:
        if isinstance(c, dict):
            cookies[c.get("name", "")] = c.get("value", "")
        elif isinstance(c, str):
            # Simple key=value format
            pass

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    await create_tables()

    async with httpx.AsyncClient(
        cookies=cookies, headers=headers, timeout=30
    ) as client:
        # 1. Fetch contest entries
        logger.info("Fetching entries for contest %s", contest_id)
        url = DK_CONTEST_ENTRIES_URL.format(contest_id=contest_id)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            entries_data = resp.json()
        except Exception as exc:
            logger.error("Failed to fetch contest entries: %s", exc)
            logger.info(
                "This likely means your cookies have expired. "
                "Re-export them from your browser."
            )
            return

        entries = entries_data.get("entries", entries_data.get("results", []))
        logger.info("Found %d entries", len(entries))

        # 2. Scrape individual lineups
        async with async_session() as db:
            from sqlalchemy import select

            # Ensure contest exists
            result = await db.execute(
                select(Contest).where(Contest.external_id == contest_id)
            )
            contest = result.scalar_one_or_none()
            if not contest:
                contest = Contest(
                    site="dk",
                    external_id=contest_id,
                    name=f"Scraped Contest {contest_id}",
                    entry_fee=0,
                    max_entries=1,
                    field_size=len(entries),
                    prize_pool=0,
                    game_type="classic",
                )
                db.add(contest)
                await db.flush()
                await db.refresh(contest)

            scraped = 0
            for entry in entries[:max_entries]:
                entry_id = entry.get("entryId") or entry.get("EntryId")
                if not entry_id:
                    continue

                # Check if already scraped
                result = await db.execute(
                    select(Lineup).where(
                        Lineup.contest_id == contest.id,
                        Lineup.entry_id == str(entry_id),
                    )
                )
                if result.scalar_one_or_none():
                    continue

                try:
                    lineup_url = DK_ENTRY_LINEUP_URL.format(entry_id=entry_id)
                    resp = await client.get(lineup_url)
                    resp.raise_for_status()
                    lineup_data = resp.json()
                except Exception as exc:
                    logger.warning("Failed to fetch entry %s: %s", entry_id, exc)
                    continue

                # Parse lineup players
                players = []
                for slot in lineup_data.get("lineupSlots", lineup_data.get("roster", [])):
                    players.append(
                        {
                            "player_id": slot.get("playerId"),
                            "position": slot.get("rosterPosition", ""),
                            "salary": slot.get("salary", 0),
                        }
                    )

                total_salary = sum(p.get("salary", 0) for p in players)
                total_points = entry.get("fantasyPoints") or entry.get("FantasyPoints")
                finish = entry.get("rank") or entry.get("Rank")

                lineup = Lineup(
                    contest_id=contest.id,
                    entry_id=str(entry_id),
                    user_name=entry.get("userName") or entry.get("UserName"),
                    players=json.dumps(players),
                    total_salary=total_salary,
                    total_points=float(total_points) if total_points else None,
                    finish_position=int(finish) if finish else None,
                    is_user=False,
                )
                db.add(lineup)
                scraped += 1

                if scraped % 100 == 0:
                    logger.info("Scraped %d/%d entries", scraped, len(entries))
                    await db.flush()

            await db.commit()
            logger.info(
                "Contest %s scrape complete: %d entries stored", contest_id, scraped
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape DraftKings contest results for lineup analysis"
    )
    parser.add_argument("--contest-id", required=True, help="DK contest ID")
    parser.add_argument(
        "--cookies",
        default="~/dk_cookies.json",
        help="Path to DK session cookies JSON",
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        default=5000,
        help="Max entries to scrape",
    )
    args = parser.parse_args()
    asyncio.run(
        scrape_contest(args.contest_id, args.cookies, args.max_entries)
    )


if __name__ == "__main__":
    main()
