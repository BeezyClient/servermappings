# Adding or updating a server

Server owners and their staff add servers with a pull request. Everything a pull request
is checked against is in `scripts/validate.py`; run it before you open one.

## Who can add a server

- The server is **public**: anyone with a Minecraft account can join. No whitelists, no
  private SMPs, no one-off events or tournament servers.
- The server runs on a **domain you own**. Free subdomains of hosting companies and
  tunnels (`*.aternos.me`, `*.minehut.gg`, `*.playit.gg`, ...) are not accepted: they
  can belong to someone else tomorrow.
- You **run or represent** the server, and prove it (below).
- The server follows the [Minecraft Usage Guidelines](https://www.minecraft.net/usage-guidelines)
  and the law. Beezy may refuse or remove any server, for example over scams, cheats
  for sale, hate, sexual content, or abuse of players.

## Step by step

1. Fork this repository.
2. Pick an **id**: lowercase letters and digits, optionally separated by single dashes,
   2-32 characters (`examplemc`, `example-network`). It never changes afterwards, so
   do not put a season or a year in it.
3. Create `servers/<id>/metadata.json` (fields below). Start from an existing server.
4. Optionally add artwork (below). No artwork is fine: Beezy draws a monogram in your
   accent colour.
5. Add the ownership proof.
6. Run `python3 scripts/validate.py` (Python 3.10+, nothing to install).
7. Open a pull request that touches only `servers/<id>/`, and fill in the template.

The **Validate** check runs on every pull request. A maintainer reviews the rest by hand
(description, artwork, the server itself), usually within a week. A merged change reaches
players with Beezy's next manifest publication, typically within a few days.

## metadata.json

```json
{
  "$schema": "../../schema/metadata.schema.json",
  "id": "examplemc",
  "name": "ExampleMC",
  "description": "Survival with player shops, claims and a weekly build contest.",
  "addresses": {
    "primary": "play.examplemc.net",
    "suffixes": ["examplemc.net", "examplemc.com"]
  },
  "accentColor": "#3399ff",
  "minecraft": { "versions": ["1.21.*", "26.1.*"], "recommended": "1.21.11" },
  "regions": ["EU"],
  "languages": ["en", "it"],
  "gamemodes": ["survival", "economy"],
  "tags": ["claims"],
  "links": {
    "website": "https://examplemc.net/",
    "discord": "https://discord.gg/examplemc",
    "store": "https://store.examplemc.net/"
  },
  "presence": { "gameName": "ExampleMC" },
  "maintainers": ["your-github-username"]
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `id` | yes | Same as the folder name. |
| `name` | yes | Up to 32 characters, as players write it. |
| `description` | recommended | One English sentence, 16-120 characters. No links, no "best server", no all caps. |
| `addresses.primary` | yes | What players type in Multiplayer: `host` or `host:port`, lowercase, on one of your suffixes. Not an address made for one particular client. |
| `addresses.ping` | no | Only if the primary name works through an SRV record: the record's target. Beezy pings this one. |
| `addresses.suffixes` | yes | Registrable domains you own, without subdomain (`examplemc.net`, not `play.examplemc.net`). Any address ending in one of them is recognised as your server. A suffix belongs to one server only. |
| `accentColor` | yes | `#rrggbb`, lowercase. |
| `minecraft.versions` | yes | Versions you accept: `1.21.11`, `1.21.*` or a release line like `26.1`. |
| `minecraft.recommended` | yes | One exact version Beezy suggests. Must be covered by `versions`. |
| `regions` | no | Where your machines are: `AF`, `AS`, `EU`, `NA`, `OC`, `SA`. |
| `languages` | no | Spoken on the server: `en`, `it`, `pt-BR`, ... |
| `gamemodes` | recommended | 1-10 values from the list in `schema/metadata.schema.json`, most important first. Missing one? Use `other` and ask in the pull request. |
| `tags` | no | Up to 8 lowercase keywords, reviewed by hand. |
| `links` | no | `website`, `discord` (a permanent `discord.gg` or `discord.com/invite` link), `store`, `wiki`, `rules`, `support`. `https://` only, no link shorteners. **The only place URLs are allowed.** |
| `presence.gameName` | no | Name in Discord Rich Presence and the friends list. Defaults to `name`. |
| `modpack` | no | `{ "project": "<modrinth slug or id>", "version": "<8-character version id>" }` if players need a Modrinth modpack to join. Beezy offers to install it before joining. |
| `offline` | no | `true` while the server is down for a while (maintenance, between seasons). It stays recognised but is not featured. Remove it when you are back. |
| `inactive` | no | Set automatically or by maintainers, see below. Do not add it yourself. |
| `maintainers` | no | GitHub usernames that may update the entry without a new ownership proof. |

## Artwork

All optional. PNG only (8 bits per channel, RGB, RGBA or palette, not interlaced, not
animated). Links to images elsewhere are not accepted: the files live in your folder.
Metadata (EXIF, text chunks) is stripped when Beezy builds the index.

| File | Size (pixels) | Max file size | Notes |
| --- | --- | --- | --- |
| `logo.png` | 512 x 512 | 512 KB | Transparent background. Your icon, readable at 32 px. |
| `banner.png` | 1280 x 320 | 1 MB | Drawn behind your server's row, darkened on the left for text. Keep important detail in the right two thirds. |
| `background.png` | 1920 x 1080 | 3 MB | A screenshot or key art. No text, no logo on it. |
| `wordmark.png` | 1024 wide, 128-512 tall | 512 KB | Transparent background. Your name as artwork. |

No text in banners and backgrounds except your own name, no prices, no "join now", nothing
that imitates Beezy or Minecraft UI, no other servers' or companies' brands, no
copyrighted material you have no right to.

## Proving you own the server

The Validate workflow checks that the pull request's author speaks for the server, with
either proof. Use your GitHub username, lowercase:

- **DNS** (preferred): a TXT record on `_beezy.<one of your suffixes>` with the value
  `beezy-servermappings=<your-github-username>`. Example: `_beezy.examplemc.net TXT
  "beezy-servermappings=octocat"`.
- **MOTD**: put `beezy-servermappings=<your-github-username>` anywhere in the server's MOTD
  until the pull request is merged.

Check it yourself with `python3 scripts/verify_owner.py <id> <your-github-username>`.
You can remove the record or the MOTD text after the merge. Add yourself to `maintainers`
and later updates from your account need no new proof.

## Updating a server

Open a pull request that changes `servers/<id>/`. If your GitHub account is in the entry's
`maintainers`, no proof is needed; otherwise prove ownership again. Renames are fine; the
`id` stays. To be removed, open a pull request that deletes the folder (with proof), or
email administration@beezyclient.com from an address on your domain.

## Inactive servers

This is automatic: every day `scripts/activity.py` pings every server. After **90 days** without
an answer a server gets `"inactive": { "since": "YYYY-MM-DD", "reason": "unreachable" }` and is
left out of Beezy; when it answers again, the flag goes away by itself. **180 days** after
`since` the folder is deleted, and the server needs a new pull request to come back.

Maintainers can also set `inactive` by hand with the reasons `closed`, `requested` or `policy`;
those are not removed automatically. For planned downtime use `offline`, which keeps you listed.

## Pull requests that get closed

- requested changes not addressed within 7 days;
- files outside `servers/<id>/`, or more than one server per pull request;
- artwork or text copied from someone else, or a server you do not represent;
- descriptions written as advertising.

Please do not ping maintainers for reviews before a week has passed.
