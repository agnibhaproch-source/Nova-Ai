"""ClamAV INSTREAM scanning (docs/18 §5). Enabled via CLAMAV_ENABLED."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

from app.core.config import get_settings


class ScanUnavailable(Exception):
    pass


async def scan(path: Path) -> str | None:
    """Returns the signature name if malware is found, None if clean."""
    s = get_settings()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(s.CLAMAV_HOST, s.CLAMAV_PORT), 10
        )
    except (OSError, TimeoutError) as e:
        raise ScanUnavailable from e
    try:
        writer.write(b"zINSTREAM\0")
        with path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()
        writer.write(struct.pack("!L", 0))
        await writer.drain()
        reply = (await asyncio.wait_for(reader.read(4096), 60)).decode(errors="replace")
    except (OSError, TimeoutError) as e:
        raise ScanUnavailable from e
    finally:
        writer.close()
    if "FOUND" in reply:
        return reply.split(":", 1)[-1].replace("FOUND", "").strip(" \0")
    if "OK" not in reply:
        raise ScanUnavailable(reply)
    return None
