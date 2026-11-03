# Beezy Server Mappings

The public list of Minecraft servers that [Beezy Client](https://beezyclient.com) knows by
name, with their addresses, versions and artwork.

Beezy uses it to:

- show servers in the launcher with their logo, background and colours;
- recognise a server from whatever address a player typed, alternative domains included;
- show "Playing on Hypixel" in Discord Rich Presence and the friends list, instead of an IP;
- suggest the right Minecraft version, and the right modpack when a server needs one.

**Run a server and want it in Beezy?** It takes one pull request: see
[CONTRIBUTING.md](CONTRIBUTING.md).

## What's in a server

Each server is a folder named after its id:

```
servers/<id>/
├─ metadata.json     required: name, addresses, colour, versions (schema/metadata.schema.json)
├─ logo.png          optional, 512×512, transparent
├─ banner.png        optional, 1280×320
├─ background.png    optional, 1920×1080
└─ wordmark.png      optional, 1024 wide, 128-512 tall, transparent
```

A minimal `metadata.json`:

```json
{
  "$schema": "../../schema/metadata.schema.json",
  "id": "examplemc",
  "name": "ExampleMC",
  "addresses": { "primary": "play.examplemc.net", "suffixes": ["examplemc.net"] },
  "accentColor": "#3399ff",
  "minecraft": { "versions": ["1.8.*", "1.21.*"], "recommended": "1.21.11" }
}
```

Description, gamemodes, regions, languages, links, Discord presence name and modpack are
optional; all fields are described in [CONTRIBUTING.md](CONTRIBUTING.md#metadatajson).

## Servers that stop answering

Nobody has to clean the list by hand. Every day [`scripts/activity.py`](scripts/activity.py)
pings every server, the same way the Multiplayer screen does, and keeps the date of its last
answer in [`status/last-seen.json`](status/last-seen.json):

| Situation | What happens |
|---|---|
| No answer for **90 days** | marked `"inactive": {"since": …, "reason": "unreachable"}`, left out of Beezy |
| An inactive server answers again | the flag is removed and it is back the next day |
| Inactive for **180 more days** | the folder is deleted |

Owners can also ask for their server to be removed, or for its artwork to be changed, with an
issue or a pull request.

## For developers

The scripts need Python 3.10+ and nothing else.

```sh
python3 scripts/validate.py                       # every rule a pull request is checked against
python3 scripts/build.py                          # builds dist/index.json and the normalised artwork
python3 scripts/activity.py --dry-run             # pings everything, changes nothing
python3 scripts/verify_owner.py <id> <github-user>
python3 -m unittest discover -s scripts -p 'test_*.py'
```

`dist/index.json` lists every active server, sorted by id:

```jsonc
{
  "formatVersion": 1,
  "generatedAt": "2026-11-03T12:00:00Z",   // commit time, so builds are reproducible
  "commit": "…",
  "servers": [
    {
      "id": "examplemc", "name": "ExampleMC",
      "addresses": { "primary": "play.examplemc.net", "suffixes": ["examplemc.net"] },
      "accentColor": "#3399ff",
      "minecraft": { "versions": ["1.8.*", "1.21.*"], "recommended": "1.21.11" },
      "images": {
        "logo": { "file": "examplemc/logo.0123456789ab.png", "width": 512, "height": 512, "bytes": 81234, "sha256": "…" }
      }
    }
  ],
  "inactive": ["closedserver"]
}
```

Artwork is rewritten without metadata (EXIF, text, timestamps) and named after a hash of its
content, so a file never changes under the same name.

## How the data reaches Beezy

The launcher never reads this repository at runtime. Beezy's release pipeline builds the index,
turns it into the launcher's `servers.json` manifest, **signs** it, and publishes the artwork
under `https://api.beezyclient.com/servermappings/`. The launcher accepts only a signed
manifest and loads artwork only from Beezy's own domain, so a merged change shows up with the
next manifest publication.

## Licence

Scripts, schema, workflows and documentation: MIT ([LICENSE](LICENSE)). Server names,
descriptions and artwork belong to their owners and are not MIT; contributing them grants
Beezy the licence described in LICENSE under "Server data and artwork". Names and logos are
trademarks of their owners; being listed is not an endorsement.
