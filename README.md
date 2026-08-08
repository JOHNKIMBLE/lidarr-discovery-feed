# lidarr-discovery-feed

A small self-hosted feed generator for [Lidarr](https://lidarr.audio/)'s
**Custom List** import type. It builds a MusicBrainz-ID artist list from radio
airplay and a record label's roster, so Lidarr keeps picking up new artists
automatically instead of relying on a manually curated list.

## What it does

`generate.py` combines three sources into one deduplicated list of
MusicBrainz artist IDs:

1. **A record label's full roster** -- queried from MusicBrainz's release
   catalog for the label. New signings get picked up as soon as their first
   release is tagged to the label on MusicBrainz.
2. **Artists played on an RTE radio show** -- scraped from RTE's own site.
   The per-episode playlist is server-rendered directly in the page HTML, so
   no browser automation is needed, just plain HTTP requests.
3. **Artists played on a BBC Radio programme** -- scraped from the official
   BBC programme pages (`bbc.co.uk/programmes/<pid>`), same approach.

Sources 2 and 3 only give plain artist names, so each name is resolved to a
MusicBrainz ID via MusicBrainz's artist search API. Only high-confidence
matches (score >= 90) are kept -- anything softer is logged and skipped
rather than risking the wrong artist landing in your library.

The result is written as `lidarr-discovery.json`:

```json
[{"MusicBrainzId": "76c9989d-99a7-4f96-8a95-2e8b3a23e75f"}, ...]
```

`serve.sh` serves that file over plain HTTP so Lidarr can pull it as a list
URL.

## Setup

1. Configure the sources you want via environment variables (see below), or
   just use the defaults.
2. Run `run.sh` on a schedule (cron, systemd timer, or your NAS/server's
   own scheduled-task mechanism) -- once or twice a day is plenty.
3. Run `serve.sh` to serve the generated JSON, or just drop the JSON file on
   any web server / static file host you already have.
4. In Lidarr, add an import list:
   - Type: **Custom List** (`CustomImport`)
   - List URL: `http://<host>:8098/lidarr-discovery.json`
   - Set **Monitor** to whatever level of the artist's catalog you want
     grabbed (e.g. "Entire Artist"), and enable **Search on Add** if you
     want new artists searched immediately rather than just added.

## Configuration

All source identifiers are environment variables so this can be repointed at
a different label or show without touching the code:

| Variable | Default | Meaning |
|---|---|---|
| `LABEL_MBID` | Ninja Tune's MusicBrainz ID | The label whose roster gets pulled |
| `MIN_RELEASES` | `1` | Minimum releases on the label before an artist counts |
| `RTE_STATION` | `2fm` | RTE station slug |
| `RTE_SHOW` | Greene Room with Jenny Greene | RTE show slug |
| `RTE_EPISODES_PER_RUN` | `12` | How many recent RTE episodes to scan |
| `BBC_SHOW_PID` | Benji B (BBC Radio 1) | BBC programme ID |
| `OUT_PATH` | `./lidarr-discovery.json` | Where the JSON feed is written |
| `LOG_PATH` | `./generate.log` | Where run logs are written |
| `MB_CONTACT` | This repository URL | Contact URL included in the MusicBrainz User-Agent |
| `PORT` (serve.sh) | `8098` | Port to serve the JSON on |

To find a different BBC programme's PID or an RTE show's slug, just look at
the URL of that show's page on bbc.co.uk/programmes or rte.ie/radio.

## Notes

- Everything here talks to public, unauthenticated endpoints (MusicBrainz,
  RTE, BBC) -- no API keys or accounts required.
- Requests are rate-limited (roughly 1/sec to MusicBrainz) to be a good
  citizen of those services.
- MusicBrainz API calls retry a few times before giving up, since a single
  dropped request mid-pagination can otherwise silently under-count a large
  label's roster.
- `run.sh` uses a non-blocking lock, and the generator atomically replaces the
  JSON feed only after a fully successful run.  A failed or overlapping run
  leaves Lidarr's last known-good feed available.
