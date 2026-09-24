"""Load-test helper (dev / staging-perf only): create N verified pro users with API keys and
print them as JSON for infra/k6. Refuses to run in production.

    uv run python -m tests.fakes.seed_load_users 20 > /tmp/k6-users.json
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models import User, UserPreferences
from app.services import api_key_service


async def main(n: int) -> None:
    if get_settings().APP_ENV == "production":
        raise SystemExit("refusing to seed load-test users in production")
    out = []
    async with get_sessionmaker()() as db:
        pw = await hash_password(f"k6-{uuid.uuid4()}")  # unusable: these accounts only use API keys
        for i in range(n):
            u = User(
                email=f"k6-{uuid.uuid4().hex[:10]}-{i}@example.com",
                password_hash=pw,
                display_name=f"k6 {i}",
                plan_key="pro",
                email_verified_at=datetime.now(UTC),
            )
            db.add(u)
            await db.flush()
            db.add(UserPreferences(user_id=u.id))
            await db.commit()
            key = await api_key_service.create(
                db,
                u.id,
                "pro",
                True,
                "k6",
                sorted(api_key_service.API_SCOPES),
                None,
                request_id="k6-seed",
            )
            out.append({"email": u.email, "api_key": key["secret"]})
    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
