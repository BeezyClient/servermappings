#!/usr/bin/env python3
"""Validates every server under servers/.

    python3 scripts/validate.py

Exit code 0 when everything passes, 1 otherwise. Offline: no DNS, no pings (that is
verify_owner.py). In GitHub Actions the errors are also printed as annotations.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CLIENT_LABELS,
    ALLOWED_FILES,
    IMAGES,
    METADATA,
    SCHEMA_PATH,
    SERVERS_DIR,
    SHARED_HOSTING,
    PngError,
    SchemaError,
    host_of,
    load_json,
    on_suffix,
    read_png,
    registrable,
    validate_schema,
)

RESERVED_TLDS = {"local", "localhost", "test", "example", "invalid", "internal", "lan", "home"}
URL_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rebrand.ly", "linktr.ee"}
CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0
        self.annotate = os.environ.get("GITHUB_ACTIONS") == "true"

    def error(self, where: Path | str, message: str) -> None:
        self.errors += 1
        self._emit("error", where, message)

    def warn(self, where: Path | str, message: str) -> None:
        self.warnings += 1
        self._emit("warning", where, message)

    def _emit(self, level: str, where: Path | str, message: str) -> None:
        shown = where
        if isinstance(where, Path) and where.is_relative_to(SERVERS_DIR.parent):
            shown = where.relative_to(SERVERS_DIR.parent)
        print(f"{level}: {shown}: {message}")
        if self.annotate and isinstance(where, Path):
            print(f"::{level} file={shown}::{message}")


def version_covers(pattern: str, version: str) -> bool:
    if pattern.endswith(".*"):
        return version.startswith(pattern[:-1])
    # "26.1" is a release line and covers 26.1 and 26.1.x.
    return version == pattern or (pattern.count(".") == 1 and version.startswith(pattern + "."))


def strings_with_urls(value: object, path: str = "$") -> list[str]:
    """Every string outside `links` that looks like a URL. Artwork is files in the folder,
    never a link to somewhere else."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if path == "$" and key in ("links", "$schema"):
                continue
            found += strings_with_urls(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += strings_with_urls(item, f"{path}[{index}]")
    elif isinstance(value, str) and re.search(r"(?i)\b[a-z][a-z0-9+.-]*://|\bwww\.", value):
        found.append(path)
    return found


def check_domain(report: Report, where: Path, label: str, host: str) -> None:
    tld = host.rsplit(".", 1)[-1]
    if tld in RESERVED_TLDS:
        report.error(where, f"{label} {host}: .{tld} is not a public domain")
    if any(on_suffix(host, shared) for shared in SHARED_HOSTING):
        report.error(where, f"{label} {host}: use a domain you own, not a shared host or tunnel")
    if host.split(".")[0] in CLIENT_LABELS:
        report.error(where, f"{label} {host}: addresses made for one particular client are not accepted")


def check_server(report: Report, folder: Path, schema: dict) -> dict | None:
    where = folder / METADATA
    for entry in sorted(folder.iterdir()):
        if entry.name not in ALLOWED_FILES:
            report.error(entry, f"unexpected file; allowed: {', '.join(sorted(ALLOWED_FILES))}")
        elif entry.is_symlink() or not entry.is_file():
            report.error(entry, "must be a regular file")
    if not where.is_file():
        report.error(folder, f"missing {METADATA}")
        return None

    raw = where.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        report.error(where, "remove the UTF-8 byte order mark")
    try:
        metadata = load_json(where)
    except (ValueError, UnicodeDecodeError) as error:
        report.error(where, f"not valid JSON: {error}")
        return None

    try:
        problems = validate_schema(metadata, schema)
    except SchemaError as error:
        report.error(SCHEMA_PATH, str(error))
        return None
    for problem in problems:
        report.error(where, problem)
    if problems or not isinstance(metadata, dict):
        return None

    if metadata["id"] != folder.name:
        report.error(where, f"id '{metadata['id']}' must equal the folder name '{folder.name}'")

    for field in ("name", "description"):
        if field in metadata and (CONTROL.search(metadata[field]) or metadata[field] != metadata[field].strip()):
            report.error(where, f"{field}: no control characters or surrounding spaces")
    if "presence" in metadata and CONTROL.search(metadata["presence"]["gameName"]):
        report.error(where, "presence.gameName: no control characters")
    for path in strings_with_urls(metadata):
        report.error(where, f"{path}: URLs are only allowed under links; artwork is a file in the folder")

    addresses = metadata["addresses"]
    suffixes = addresses["suffixes"]
    for suffix in suffixes:
        if registrable(suffix) != suffix:
            report.error(where, f"suffix {suffix}: list the registrable domain ({registrable(suffix)}), not a subdomain")
        check_domain(report, where, "suffix", suffix)
    primary = host_of(addresses["primary"])
    check_domain(report, where, "primary address", primary)
    if not any(on_suffix(primary, suffix) for suffix in suffixes):
        report.error(where, f"primary address {primary} is not on one of the suffixes")
    if "ping" in addresses:
        ping = host_of(addresses["ping"])
        check_domain(report, where, "ping address", ping)
        if not any(on_suffix(ping, suffix) for suffix in suffixes):
            report.warn(where, f"ping address {ping} is not on your suffixes; a reviewer will check the SRV record")
        if addresses["ping"] == addresses["primary"]:
            report.error(where, "ping equals primary: leave ping out")
    for address in [addresses["primary"], addresses.get("ping")]:
        if address and ":" in address and not 0 < int(address.rsplit(":", 1)[1]) < 65536:
            report.error(where, f"{address}: port out of range")

    minecraft = metadata["minecraft"]
    if not any(version_covers(pattern, minecraft["recommended"]) for pattern in minecraft["versions"]):
        report.error(where, f"minecraft.recommended {minecraft['recommended']} is not covered by minecraft.versions")

    for key, url in metadata.get("links", {}).items():
        host = url.split("/", 3)[2]
        if host in URL_SHORTENERS:
            report.error(where, f"links.{key}: link the real page, not a shortener or link list")

    if "inactive" in metadata:
        try:
            since = dt.date.fromisoformat(metadata["inactive"]["since"])
        except ValueError:
            report.error(where, "inactive.since is not a real date")
        else:
            if since > dt.date.today():
                report.error(where, "inactive.since is in the future")

    for name, spec in IMAGES.items():
        path = folder / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > spec.max_bytes:
            report.error(path, f"{len(data) // 1024} KB, limit {spec.max_bytes // 1024} KB")
        try:
            info = read_png(data)
        except PngError as error:
            report.error(path, str(error))
            continue
        if info.width != spec.width or not spec.min_height <= info.height <= spec.max_height:
            report.error(path, f"is {info.width}x{info.height}, must be {spec.size_text()}")
        if spec.needs_alpha and not info.has_alpha:
            report.error(path, "needs a transparent background (RGBA)")
    return metadata


def main() -> int:
    report = Report()
    schema = load_json(SCHEMA_PATH)
    folders = []
    for path in sorted(SERVERS_DIR.iterdir()):
        if path.is_dir() and not path.is_symlink():
            folders.append(path)
        else:
            report.error(path, "only server folders belong in servers/")

    parsed: dict[str, dict] = {}
    for folder in folders:
        metadata = check_server(report, folder, schema)
        if metadata is not None:
            parsed[folder.name] = metadata

    # Cross-server rules: a name, a suffix or an address belongs to one server only.
    owners: dict[str, str] = {}
    for server_id, metadata in sorted(parsed.items()):
        where = SERVERS_DIR / server_id / METADATA
        claims = [("name", metadata["name"].casefold())]
        claims += [("suffix", suffix) for suffix in metadata["addresses"]["suffixes"]]
        claims.append(("address", host_of(metadata["addresses"]["primary"])))
        for kind, value in claims:
            owner = owners.setdefault(f"{kind}:{value}", server_id)
            if owner != server_id:
                report.error(where, f"{kind} '{value}' is already used by '{owner}'")

    print(f"{len(folders)} server(s) checked, {report.errors} error(s), {report.warnings} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
