#!/usr/bin/env python3
"""Builds dist/: the index Beezy consumes and the normalised artwork.

    python3 scripts/build.py [--out dist]

    dist/index.json                      every active server, sorted by id
    dist/<id>/<kind>.<sha256[:12]>.png   artwork without metadata chunks

File names carry a hash of their content, so a published image never changes under
the same URL and can be cached forever; a new logo is a new file name.

Runs the validator first and refuses to build on any error. The output is
reproducible: the timestamp is the commit time (or SOURCE_DATE_EPOCH), not "now".
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate  # noqa: E402
from common import IMAGES, METADATA, ROOT, SERVERS_DIR, load_json, normalise_png, read_png  # noqa: E402

INDEX_FORMAT = 1

# Order of the fields in the index, so diffs between two builds stay readable.
FIELDS = (
    "id", "name", "description", "addresses", "accentColor", "minecraft", "regions",
    "languages", "gamemodes", "tags", "links", "presence", "modpack", "offline",
)


def git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def build_time() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH") or git("show", "-s", "--format=%ct", "HEAD")
    moment = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc) if epoch else dt.datetime.now(dt.timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def entry_for(metadata: dict) -> dict:
    entry = {key: metadata[key] for key in FIELDS if key in metadata}
    entry.setdefault("regions", [])
    entry.setdefault("languages", [])
    entry.setdefault("tags", [])
    entry.setdefault("links", {})
    entry.setdefault("presence", {"gameName": metadata["name"]})
    entry["offline"] = bool(metadata.get("offline", False))
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    if validate.main() != 0:
        print("build: fix the validation errors first", file=sys.stderr)
        return 1

    out: Path = args.out.resolve()
    if out == ROOT or ROOT.is_relative_to(out):
        print("build: refusing to write over the repository", file=sys.stderr)
        return 1
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    servers = []
    inactive = []
    for folder in sorted(path for path in SERVERS_DIR.iterdir() if path.is_dir()):
        metadata = load_json(folder / METADATA)
        if "inactive" in metadata:
            inactive.append(metadata["id"])
            continue
        entry = entry_for(metadata)
        images = {}
        for name in IMAGES:
            source = folder / name
            if not source.is_file():
                continue
            info = read_png(source.read_bytes())
            data = normalise_png(info)
            digest = hashlib.sha256(data).hexdigest()
            kind = name.removesuffix(".png")
            relative = f"{metadata['id']}/{kind}.{digest[:12]}.png"
            target = out / relative
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
            images[kind] = {
                "file": relative,
                "width": info.width,
                "height": info.height,
                "bytes": len(data),
                "sha256": digest,
            }
        entry["images"] = images
        servers.append(entry)

    index = {
        "formatVersion": INDEX_FORMAT,
        "generatedAt": build_time(),
        "commit": git("rev-parse", "HEAD"),
        "servers": servers,
        "inactive": inactive,
    }
    (out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artwork = sum(len(server["images"]) for server in servers)
    print(f"build: {len(servers)} server(s), {artwork} image(s), {len(inactive)} inactive -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
