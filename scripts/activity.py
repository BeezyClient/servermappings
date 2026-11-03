#!/usr/bin/env python3
"""Keeps the inactive flags up to date by itself. Run daily by the Activity workflow.

    python3 scripts/activity.py [--today YYYY-MM-DD] [--dry-run]

1. Pings every listed server (Server List Ping, the same request the Multiplayer screen sends;
   `addresses.ping` when set, else the primary address and its SRV record).
2. Records the date of the last answer in status/last-seen.json.
3. A server that has not answered for INACTIVE_AFTER days gets
   `"inactive": {"since": <last answer>, "reason": "unreachable"}` and leaves the index.
4. An inactive server that answers again loses the flag, if it was set for "unreachable"
   (other reasons are set by hand and stay).
5. A server inactive for DELETE_AFTER more days is deleted, folder and all.

A server never seen since it was added counts from the day it was added to last-seen.json.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import json
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import METADATA, SERVERS_DIR, load_json  # noqa: E402
from verify_owner import read_exact, read_varint, varint  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAST_SEEN = ROOT / "status" / "last-seen.json"
INACTIVE_AFTER = 90
DELETE_AFTER = 180
TIMEOUT = 6
ATTEMPTS = 3


def srv_target(host: str) -> tuple[str, int] | None:
    """The `_minecraft._tcp` SRV record of a host, through `dig` (present on the runners)."""
    try:
        out = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", "SRV", f"_minecraft._tcp.{host}"],
            capture_output=True, text=True, timeout=10,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) >= 4 and out[2].isdigit():
        return out[3].rstrip("."), int(out[2])
    return None


def answers(address: str) -> bool:
    """Whether the server answers a status request with a JSON status."""
    host, _, port_text = address.partition(":")
    port = int(port_text) if port_text else 25565
    if not port_text:
        target = srv_target(host)
        if target:
            host, port = target
    for _ in range(ATTEMPTS):
        try:
            with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
                sock.settimeout(TIMEOUT)
                name = address.partition(":")[0].encode()
                handshake = b"\x00" + varint(-1) + varint(len(name)) + name + struct.pack(">H", port) + varint(1)
                sock.sendall(varint(len(handshake)) + handshake + b"\x01\x00")
                length = read_varint(sock)
                if not 0 < length <= 1 << 21:
                    continue
                body = read_exact(sock, length)
                start = body.find(b"{")
                if body[:1] == b"\x00" and start > 0:
                    json.loads(body[start:].decode("utf-8", "replace"))
                    return True
        except (OSError, ValueError):
            continue
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    parser.add_argument("--dry-run", action="store_true", help="ping and report, change nothing")
    args = parser.parse_args(argv)
    today = args.today

    seen: dict[str, str] = load_json(LAST_SEEN) if LAST_SEEN.exists() else {}
    folders = sorted(p for p in SERVERS_DIR.iterdir() if (p / METADATA).is_file())
    servers = {p.name: load_json(p / METADATA) for p in folders}

    def address(meta: dict) -> str:
        return meta["addresses"].get("ping") or meta["addresses"]["primary"]

    with futures.ThreadPoolExecutor(32) as pool:
        up = dict(zip(servers, pool.map(lambda m: answers(address(m)), servers.values())))

    changes: list[str] = []
    for sid, meta in servers.items():
        path = SERVERS_DIR / sid / METADATA
        inactive = meta.get("inactive")
        if up[sid]:
            seen[sid] = today.isoformat()
            if inactive and inactive.get("reason") == "unreachable":
                del meta["inactive"]
                changes.append(f"{sid}: back online")
                if not args.dry_run:
                    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            continue
        last = dt.date.fromisoformat(seen.setdefault(sid, today.isoformat()))
        if inactive:
            since = dt.date.fromisoformat(inactive["since"])
            if (today - since).days >= DELETE_AFTER:
                changes.append(f"{sid}: deleted, inactive since {since}")
                if not args.dry_run:
                    shutil.rmtree(SERVERS_DIR / sid)
                    seen.pop(sid, None)
        elif (today - last).days >= INACTIVE_AFTER:
            meta["inactive"] = {"since": last.isoformat(), "reason": "unreachable"}
            changes.append(f"{sid}: inactive, no answer since {last}")
            if not args.dry_run:
                path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for gone in set(seen) - set(servers):
        seen.pop(gone)
    if not args.dry_run:
        LAST_SEEN.parent.mkdir(exist_ok=True)
        LAST_SEEN.write_text(json.dumps(dict(sorted(seen.items())), indent=2) + "\n", encoding="utf-8")

    print(f"{sum(up.values())}/{len(up)} servers answered")
    for line in changes:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
