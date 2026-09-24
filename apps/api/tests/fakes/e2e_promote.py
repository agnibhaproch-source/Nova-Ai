"""E2E helper (test-only): put the Playwright account on the pro plan, so
the suite isn't blocked by the free plan's chat rate limit. Usage: python -m tests.fakes.e2e_promote <email>"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, update

from app.db.session import get_sessionmaker
from app.models import User
from app.services.auth_service import invalidate_user_sessions_cache


async def main(email: str) -> None:
    async with get_sessionmaker()() as db:
        uid = await db.scalar(select(User.id).where(User.email == email.lower()))
        if uid is None:
            raise SystemExit(f"no user {email}")
        await db.execute(update(User).where(User.id == uid).values(plan_key="pro"))
        await db.commit()
        await invalidate_user_sessions_cache(db, uid)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
