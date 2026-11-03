#!/usr/bin/env python3
"""Checks that a GitHub user speaks for a server.

    python3 scripts/verify_owner.py <server-id> <github-username>

Passes when either proof is in place (CONTRIBUTING.md, "Proving you own the server"):

  DNS   a TXT record on _beezy.<suffix>, for any of the server's suffixes, whose value is
        beezy-servermappings=<github-username>
  MOTD  the server's MOTD, as the multiplayer ping returns it, contains
        beezy-servermappings=<github-username>

The username is compared case-insensitively. DNS is asked over HTTPS (Cloudflare and
Google resolvers), so this needs no packages. Exit code 0 when proven, 1 when not,
2 on a usage error.
"""

from __future__ import annotations

import json
import re
import socket
import struct
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import METADATA, SERVERS_DIR, load_json  # noqa: E402

RESOLVERS = ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve")
TIMEOUT = 8
USERNAME = re.compile(r"^[A-Za-z0-9](-?[A-Za-z0-9]){0,38}$")


def token(user: str) -> str:
    return f"beezy-servermappings={user.lower()}"


def txt_records(name: str) -> list[str]:
    for resolver in RESOLVERS:
        url = f"{resolver}?{urllib.parse.urlencode({'name': name, 'type': 'TXT'})}"
        request = urllib.request.Request(url, headers={"accept": "application/dns-json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                answer = json.load(response)
        except (OSError, ValueError):
            continue
        records = []
        for record in answer.get("Answer", []):
            if record.get("type") == 16:
                # TXT data comes quoted, long values split into several quoted strings.
                records.append("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', record.get("data", ""))) or record.get("data", ""))
        return records
    return []


def varint(value: int) -> bytes:
    out = bytearray()
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def read_varint(sock: socket.socket) -> int:
    result = 0
    for shift in range(0, 35, 7):
        byte = sock.recv(1)
        if not byte:
            raise OSError("connection closed")
        result |= (byte[0] & 0x7F) << shift
        if not byte[0] & 0x80:
            return result
    raise OSError("varint too long")


def read_exact(sock: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(min(65536, length - len(data)))
        if not chunk:
            raise OSError("connection closed")
        data.extend(chunk)
    return bytes(data)


def flatten(component: object) -> str:
    if isinstance(component, str):
        return component
    if isinstance(component, list):
        return "".join(flatten(part) for part in component)
    if isinstance(component, dict):
        return flatten(component.get("text", "")) + flatten(component.get("extra", []))
    return ""


def motd(address: str) -> str:
    host, _, port_text = address.partition(":")
    port = int(port_text or 25565)
    with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
        host_bytes = host.encode()
        handshake = b"\x00" + varint(-1) + varint(len(host_bytes)) + host_bytes + struct.pack(">H", port) + varint(1)
        sock.sendall(varint(len(handshake)) + handshake + b"\x01\x00")
        length = read_varint(sock)
        if length > 1 << 21:
            raise OSError("status response too large")
        body = read_exact(sock, length)
    # packet id (varint 0) then a string: varint length + JSON.
    offset = 1
    shift = size = 0
    while True:
        byte = body[offset]
        offset += 1
        size |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            break
    status = json.loads(body[offset:offset + size].decode("utf-8"))
    return re.sub(r"§.", "", flatten(status.get("description", "")))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not USERNAME.match(argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    server_id, user = argv
    path = SERVERS_DIR / server_id / METADATA
    if not path.is_file():
        print(f"verify: no {path}", file=sys.stderr)
        return 2
    metadata = load_json(path)
    wanted = token(user)

    for suffix in metadata["addresses"]["suffixes"]:
        name = f"_beezy.{suffix}"
        if any(wanted in record.lower() for record in txt_records(name)):
            print(f"verify: {server_id}: proven by the TXT record on {name}")
            return 0
        print(f"verify: {server_id}: no matching TXT record on {name}")

    for address in dict.fromkeys(filter(None, (metadata["addresses"].get("ping"), metadata["addresses"]["primary"]))):
        try:
            text = motd(address)
        except (OSError, ValueError, IndexError) as error:
            print(f"verify: {server_id}: could not ping {address} ({error})")
            continue
        if wanted in text.lower():
            print(f"verify: {server_id}: proven by the MOTD of {address}")
            return 0
        print(f"verify: {server_id}: the MOTD of {address} does not contain the token")

    print(f"verify: {server_id}: not proven. Add `{wanted}` as described in CONTRIBUTING.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
