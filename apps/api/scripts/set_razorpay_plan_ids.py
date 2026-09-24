"""Store Razorpay plan ids on the paid plans (docs/47 §9, runbooks/billing-webhooks.md).

uv run python -m scripts.set_razorpay_plan_ids --plus plan_XXXX --pro plan_YYYY
"""

from __future__ import annotations

import argparse
import asyncio
import re

from sqlalchemy import update

from app.db.session import get_sessionmaker
from app.models import Plan

PLAN_ID = re.compile(r"^plan_[A-Za-z0-9]{6,}$")


async def main(ids: dict[str, str]) -> None:
    async with get_sessionmaker()() as db:
        for key, pid in ids.items():
            res = await db.execute(update(Plan).where(Plan.key == key).values(razorpay_plan_id=pid))
            if res.rowcount != 1:  # type: ignore[attr-defined]
                raise SystemExit(f"plan '{key}' not found")
        await db.commit()
    print("updated:", ", ".join(f"{k}={v}" for k, v in ids.items()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plus", required=True)
    ap.add_argument("--pro", required=True)
    a = ap.parse_args()
    for v in (a.plus, a.pro):
        if not PLAN_ID.match(v):
            raise SystemExit(f"not a Razorpay plan id: {v}")
    asyncio.run(main({"plus": a.plus, "pro": a.pro}))
