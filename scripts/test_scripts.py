#!/usr/bin/env python3
"""Tests for the validator and the PNG handling. `python3 -m unittest discover scripts`."""

from __future__ import annotations

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import validate  # noqa: E402


def png(width: int, height: int, color: int = 6, extra: list[tuple[bytes, bytes]] | None = None) -> bytes:
    channels = common.CHANNELS[color]
    raw = b"".join(b"\x00" + b"\x80" * (width * channels) for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    out = common.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
    for kind, body in extra or []:
        out += chunk(kind, body)
    return out + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def metadata(server_id: str = "example", **overrides: object) -> dict:
    base = {
        "id": server_id,
        "name": server_id.title(),
        "description": "A test server used by the validator's own tests.",
        "addresses": {"primary": f"play.{server_id}.net", "suffixes": [f"{server_id}.net"]},
        "accentColor": "#123abc",
        "minecraft": {"versions": ["1.21.*"], "recommended": "1.21.11"},
        "gamemodes": ["survival"],
    }
    base.update(overrides)
    return base


class PngTests(unittest.TestCase):
    def test_a_valid_png_is_read(self) -> None:
        info = common.read_png(png(512, 512))
        self.assertEqual((info.width, info.height, info.has_alpha), (512, 512, True))

    def test_rgb_has_no_alpha(self) -> None:
        self.assertFalse(common.read_png(png(8, 8, color=2)).has_alpha)

    def test_a_bad_crc_is_rejected(self) -> None:
        data = bytearray(png(8, 8))
        data[30] ^= 0xFF
        with self.assertRaises(common.PngError):
            common.read_png(bytes(data))

    def test_truncated_and_foreign_files_are_rejected(self) -> None:
        for data in (png(8, 8)[:-6], b"GIF89a....", png(8, 8) + b"junk"):
            with self.assertRaises(common.PngError):
                common.read_png(data)

    def test_animation_is_rejected(self) -> None:
        with self.assertRaises(common.PngError):
            common.read_png(png(8, 8, extra=[(b"acTL", b"\x00" * 8)]))

    def test_normalising_drops_metadata_and_keeps_pixels(self) -> None:
        source = png(8, 8, extra=[(b"tEXt", b"Author\x00someone"), (b"eXIf", b"MM\x00*")])
        clean = common.normalise_png(common.read_png(source))
        self.assertNotIn(b"tEXt", clean)
        self.assertNotIn(b"eXIf", clean)
        self.assertEqual(common.read_png(clean).width, 8)


class DomainTests(unittest.TestCase):
    def test_registrable(self) -> None:
        self.assertEqual(common.registrable("play.example.net"), "example.net")
        self.assertEqual(common.registrable("mc.example.co.uk"), "example.co.uk")

    def test_versions(self) -> None:
        self.assertTrue(validate.version_covers("1.8.*", "1.8.9"))
        self.assertTrue(validate.version_covers("26.1", "26.1.2"))
        self.assertFalse(validate.version_covers("1.8.*", "1.18.2"))
        self.assertFalse(validate.version_covers("1.21.4", "1.21.11"))


class ValidatorTests(unittest.TestCase):
    def run_validator(self, servers: list[dict], files: dict[str, bytes] | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "servers"
            for server in servers:
                folder = root / server["id"]
                folder.mkdir(parents=True)
                (folder / "metadata.json").write_text(json.dumps(server))
            for name, data in (files or {}).items():
                (root / name).write_bytes(data)
            saved = validate.SERVERS_DIR
            validate.SERVERS_DIR = root
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    code = validate.main()
            finally:
                validate.SERVERS_DIR = saved
        text = out.getvalue()
        self.assertEqual(code == 0, " 0 error(s)" in text)
        return text

    def assertOk(self, text: str) -> None:
        self.assertIn(" 0 error(s)", text, text)

    def assertError(self, text: str, fragment: str) -> None:
        self.assertNotIn(" 0 error(s)", text)
        self.assertIn(fragment, text)

    def test_a_good_server_passes(self) -> None:
        self.assertOk(self.run_validator([metadata()]))

    def test_the_seeded_repository_passes(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(validate.main(), 0, out.getvalue())

    def test_good_artwork_passes(self) -> None:
        files = {"example/logo.png": png(512, 512), "example/banner.png": png(1280, 320, color=2)}
        self.assertOk(self.run_validator([metadata()], files))

    def test_wrong_artwork_fails(self) -> None:
        self.assertError(self.run_validator([metadata()], {"example/logo.png": png(500, 500)}), "must be 512x512")
        self.assertError(self.run_validator([metadata()], {"example/logo.png": png(512, 512, color=2)}), "transparent")
        self.assertError(self.run_validator([metadata()], {"example/logo.jpg": b"x"}), "unexpected file")

    def test_the_id_matches_the_folder(self) -> None:
        server = metadata()
        server["id"] = "other"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "servers" / "example"
            folder.mkdir(parents=True)
            (folder / "metadata.json").write_text(json.dumps(server))
            saved, validate.SERVERS_DIR = validate.SERVERS_DIR, folder.parent
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    validate.main()
            finally:
                validate.SERVERS_DIR = saved
        self.assertIn("must equal the folder name", out.getvalue())

    def test_addresses(self) -> None:
        self.assertError(
            self.run_validator([metadata(addresses={"primary": "play.other.net", "suffixes": ["example.net"]})]),
            "not on one of the suffixes",
        )
        self.assertError(
            self.run_validator([metadata(addresses={"primary": "a.b.example.net", "suffixes": ["b.example.net"]})]),
            "not a subdomain",
        )
        self.assertError(
            self.run_validator([metadata(addresses={"primary": "mine.aternos.me", "suffixes": ["aternos.me"]})]),
            "shared host",
        )

    def test_a_suffix_and_a_name_belong_to_one_server(self) -> None:
        clash = metadata("second", addresses={"primary": "mc.first.net", "suffixes": ["first.net"]})
        self.assertError(self.run_validator([metadata("first"), clash]), "already used by 'first'")
        twin = metadata("third", name="First")
        self.assertError(self.run_validator([metadata("first"), twin]), "name 'first'")

    def test_urls_live_only_under_links(self) -> None:
        self.assertError(
            self.run_validator([metadata(description="Join us now at https://example.net today!")]),
            "only allowed under links",
        )
        self.assertError(self.run_validator([metadata(links={"website": "http://example.net"})]), "links.website")
        self.assertError(self.run_validator([metadata(links={"discord": "https://bit.ly/abc"})]), "links.discord")
        self.assertOk(self.run_validator([metadata(links={"discord": "https://discord.gg/abc123"})]))

    def test_the_recommended_version_is_offered(self) -> None:
        self.assertError(
            self.run_validator([metadata(minecraft={"versions": ["1.8.*"], "recommended": "1.21.11"})]),
            "not covered",
        )

    def test_unknown_fields_are_refused(self) -> None:
        self.assertError(self.run_validator([metadata(logoUrl="x")]), "unknown field 'logoUrl'")


if __name__ == "__main__":
    unittest.main()
