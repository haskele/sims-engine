"""Run the daily projection pipeline from the command line."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


async def main() -> None:
    from services.daily_pipeline import _run_cli

    target_date = sys.argv[1] if len(sys.argv) > 1 else "2026-04-14"
    site = sys.argv[2] if len(sys.argv) > 2 else "dk"
    await _run_cli(target_date, site)


if __name__ == "__main__":
    asyncio.run(main())
