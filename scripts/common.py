"""Shared helpers for validate.py, build.py and verify_owner.py.

Standard library only, on purpose: CI installs nothing, and a contributor can run
the same checks with any Python 3.10+.
"""

from __future__ import annotations

import json
import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# CI points this at the pull request's checkout while running the scripts of the base branch,
# so a pull request cannot change the rules it is checked against.
SERVERS_DIR = Path(os.environ.get("SERVERMAPPINGS_SERVERS_DIR") or ROOT / "servers").resolve()
SCHEMA_PATH = ROOT / "schema" / "metadata.schema.json"

METADATA = "metadata.json"


@dataclass(frozen=True)
class ImageSpec:
    """What one optional artwork file must look like."""

    name: str
    width: int
    min_height: int
    max_height: int
    max_bytes: int
    needs_alpha: bool
    purpose: str

    def size_text(self) -> str:
        if self.min_height == self.max_height:
            return f"{self.width}x{self.min_height}"
        return f"{self.width}x{self.min_height}..{self.max_height}"


IMAGES: dict[str, ImageSpec] = {
    spec.name: spec
    for spec in (
        ImageSpec("logo.png", 512, 512, 512, 512 * 1024, True, "square icon in lists"),
        ImageSpec("banner.png", 1280, 320, 320, 1024 * 1024, False, "wide strip behind the server row"),
        ImageSpec("background.png", 1920, 1080, 1080, 3 * 1024 * 1024, False, "full-page backdrop"),
        ImageSpec("wordmark.png", 1024, 128, 512, 512 * 1024, True, "the server's name as artwork"),
    )
}

ALLOWED_FILES = {METADATA, *IMAGES}

# Second-level labels under which a registrable domain has three labels (example.co.uk).
# Not the full Public Suffix List: enough for the domains Minecraft servers use, and a
# reviewer looks at every new suffix anyway.
COMPOUND_TLDS = {
    "co.uk", "org.uk", "me.uk", "com.au", "net.au", "org.au", "com.br", "net.br", "com.tr",
    "com.mx", "com.ar", "co.nz", "co.za", "com.pl", "co.jp", "co.kr", "com.cn", "com.tw",
    "com.hk", "com.sg", "co.id", "com.vn", "com.ua", "com.ru", "co.in", "co.il", "com.es",
}

# First labels of addresses a server sets up for one particular client (a separate entry point
# for that client's players). Such an address is not how everyone joins the server.
CLIENT_LABELS = {"lunar", "badlion", "blc", "feather", "labymod", "lc", "pvplounge"}

# Free hosting and tunnel domains. A subdomain of one of these is not the server's own
# address: it can be handed to someone else tomorrow.
SHARED_HOSTING = {
    "aternos.me", "aternos.host", "aternos.org", "minehut.gg", "minehut.com", "exaroton.me",
    "falixsrv.me", "falix.gg", "ploudos.me", "playit.gg", "joinmc.link", "ngrok.io", "ngrok.app",
    "feathermc.gg", "e4mc.link", "serv.nu", "mcpro.io", "hosting.me", "minefort.com",
    # Beezy's own Hosted Worlds addresses are temporary by design.
    "beezyclient.com",
}


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def registrable(domain: str) -> str:
    """The registrable part of a host name (play.example.co.uk -> example.co.uk)."""
    labels = domain.lower().strip(".").split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in COMPOUND_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_of(address: str) -> str:
    return address.rsplit(":", 1)[0] if ":" in address else address


def on_suffix(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


# --------------------------------------------------------------------- schema --


class SchemaError(Exception):
    pass


def validate_schema(value: object, schema: dict, root: dict | None = None, where: str = "$") -> list[str]:
    """Checks `value` against the subset of JSON Schema our schema file uses.

    Supported: $ref (local), type, enum, required, properties, additionalProperties: false,
    items, minItems, maxItems, uniqueItems, minLength, maxLength, pattern. Anything else in
    the schema raises SchemaError, so the schema cannot silently grow a rule nobody enforces.
    """
    root = root if root is not None else schema
    errors: list[str] = []
    known = {
        "$schema", "$id", "$defs", "title", "description", "$ref", "type", "enum", "required",
        "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
        "minLength", "maxLength", "pattern",
    }
    unknown = set(schema) - known
    if unknown:
        raise SchemaError(f"schema keyword(s) not supported by the validator: {sorted(unknown)}")

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise SchemaError(f"only local $refs are supported: {ref}")
        return validate_schema(value, root["$defs"][ref[len("#/$defs/"):]], root, where)

    expected = schema.get("type")
    type_ok = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    }
    if expected is not None and not type_ok[expected](value):
        return [f"{where}: expected {expected}"]

    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {json.dumps(value)} is not one of {', '.join(map(str, schema['enum']))}"]

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: {json.dumps(value)} does not match {schema['pattern']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: at most {schema['maxItems']} item(s)")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(seen) != len(set(seen)):
                errors.append(f"{where}: items must be unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += validate_schema(item, schema["items"], root, f"{where}[{index}]")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing required field '{key}'")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors += validate_schema(item, properties[key], root, f"{where}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}: unknown field '{key}'")
    return errors


# ------------------------------------------------------------------------ png --

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Chunks kept by normalise_png: what is needed to draw the pixels in the right colours.
# Text, EXIF, timestamps and anything unknown are dropped.
KEPT_CHUNKS = {b"IHDR", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"IDAT", b"IEND"}

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(Exception):
    pass


@dataclass
class PngInfo:
    width: int
    height: int
    bit_depth: int
    color_type: int
    has_alpha: bool
    chunks: list[tuple[bytes, bytes]]


def read_png(data: bytes) -> PngInfo:
    """Parses and fully checks a PNG: signature, CRCs, header, and that the pixel data
    inflates to exactly the size the header promises. Raises PngError otherwise."""
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("not a PNG file (wrong signature)")
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
        if offset + 12 > len(data):
            raise PngError("truncated chunk")
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + length]
        if len(body) != length or offset + 12 + length > len(data):
            raise PngError("truncated chunk")
        (crc,) = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise PngError(f"bad CRC in {kind.decode('latin-1')} chunk")
        chunks.append((kind, body))
        offset += 12 + length
        if kind == b"IEND":
            break
    if offset != len(data):
        raise PngError("data after the end of the image")
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise PngError("missing IHDR")
    if chunks[-1][0] != b"IEND":
        raise PngError("missing IEND")
    kinds = {kind for kind, _ in chunks}
    if b"acTL" in kinds:
        raise PngError("animated PNGs are not accepted")

    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if width == 0 or height == 0 or width > 4096 or height > 4096:
        raise PngError(f"unreasonable size {width}x{height}")
    if color not in (2, 3, 6):
        raise PngError("use RGB, RGBA or palette colour (no greyscale)")
    if depth != 8:
        raise PngError(f"use 8 bits per channel (this file has {depth})")
    if compression != 0 or filtering != 0:
        raise PngError("unknown compression or filter method")
    if interlace != 0:
        raise PngError("interlaced PNGs are not accepted; export without interlacing")
    if color == 3 and b"PLTE" not in kinds:
        raise PngError("palette image without a palette")

    stride = 1 + width * CHANNELS[color]
    expected = stride * height
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"), expected + 1)
    except zlib.error as error:
        raise PngError(f"corrupt pixel data ({error})") from None
    if len(raw) != expected or not inflater.eof:
        raise PngError("pixel data does not match the image size")
    if any(raw[row * stride] > 4 for row in range(height)):
        raise PngError("corrupt pixel data (bad filter byte)")

    has_alpha = color == 6 or b"tRNS" in kinds
    return PngInfo(width, height, depth, color, has_alpha, chunks)


def normalise_png(info: PngInfo) -> bytes:
    """The same pixels without metadata: kept chunks only, IDAT merged into one."""
    out = bytearray(PNG_SIGNATURE)

    def chunk(kind: bytes, body: bytes) -> None:
        out.extend(struct.pack(">I", len(body)))
        out.extend(kind + body)
        out.extend(struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    idat = b"".join(body for kind, body in info.chunks if kind == b"IDAT")
    wrote_idat = False
    for kind, body in info.chunks:
        if kind not in KEPT_CHUNKS:
            continue
        if kind == b"IDAT":
            if not wrote_idat:
                chunk(b"IDAT", idat)
                wrote_idat = True
            continue
        chunk(kind, body)
    return bytes(out)
