#!/usr/bin/env python3
"""Generates a Lidarr "Custom List" JSON feed for artist discovery.

Combines three sources into one deduplicated artist list:

  1. A record label's full artist roster, derived from MusicBrainz's release
     catalog for that label. MIN_RELEASES=1 by default so a brand-new signing
     is caught the moment their first release is tagged to the label.
  2. Artists played on a given radio show, scraped from the show's own site
     (tested against RTE 2FM, whose per-episode playlist is server-rendered
     directly in the page HTML -- no browser/JS needed).
  3. Artists played on a BBC Radio programme, scraped from the official BBC
     programme pages (bbc.co.uk/programmes/<pid>) -- also server-rendered,
     no browser needed.

Sources 2 and 3 give plain artist names, not MusicBrainz IDs, so each name is
resolved via MusicBrainz's artist search API. Only high-confidence matches
(score >= 90) are kept; anything softer is logged and skipped rather than
risking a wrong artist ending up in the list.

Output: a flat JSON array of {"MusicBrainzId": "<mbid>"}, the exact format
Lidarr's "Custom List" (CustomImport) import type expects as a list URL.

All source identifiers below are configurable via environment variables so
this can be repointed at a different label/show without touching the code.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

UA = "lidarr-discovery-feed/1.0 (personal use; contact via github)"

# --- Label roster (MusicBrainz) ---------------------------------------------
LABEL_MBID = os.environ.get("LABEL_MBID", "dc940013-b8a8-4362-a465-291026c04b42")  # Ninja Tune
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"
MIN_RELEASES = int(os.environ.get("MIN_RELEASES", "1"))  # 1 catches new signings immediately

# --- RTE radio show ----------------------------------------------------------
RTE_STATION = os.environ.get("RTE_STATION", "2fm")
RTE_SHOW = os.environ.get("RTE_SHOW", "2fm-greene-room-with-jenny-greene")
RTE_EPISODES_PER_RUN = int(os.environ.get("RTE_EPISODES_PER_RUN", "12"))  # ~2-3 weeks of shows

# --- BBC radio show -----------------------------------------------------------
BBC_SHOW_PID = os.environ.get("BBC_SHOW_PID", "b00v4tv3")  # Benji B, BBC Radio 1

OUT_PATH = os.environ.get("OUT_PATH", "./lidarr-discovery.json")
LOG_PATH = os.environ.get("LOG_PATH", "./generate.log")

MB_RETRIES = 3
MB_RETRY_BACKOFF = 3  # seconds, multiplied by attempt number


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    print(line)
    with open(LOG_PATH, "a") as fh:
        fh.write(line + "\n")


def http_get(url, headers=None):
    cmd = ["curl", "-sL", "--max-time", "20", "-A", UA]
    for k, v in (headers or {}).items():
        cmd += ["-H", "%s: %s" % (k, v)]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def mb_get(path):
    """GET against the MusicBrainz API with retries.

    MusicBrainz occasionally times out or rate-limits mid-pagination; without
    a retry, a single dropped request silently truncates results (e.g. a
    label roster fetch stopping partway through and under-reporting artists).
    """
    for attempt in range(1, MB_RETRIES + 1):
        raw = http_get("https://musicbrainz.org/ws/2/" + path)
        try:
            return json.loads(raw)
        except Exception:
            if attempt < MB_RETRIES:
                time.sleep(MB_RETRY_BACKOFF * attempt)
    log("  [musicbrainz] giving up after %d attempts: %s" % (MB_RETRIES, path))
    return None


def resolve_name_to_mbid(name, source):
    q = urllib.parse.quote('artist:"%s"' % name)
    d = mb_get("artist/?query=%s&fmt=json&limit=3" % q)
    if not d:
        return None
    artists = d.get("artists", [])
    if not artists:
        return None
    best = artists[0]
    if int(best.get("score", 0)) >= 90:
        return best.get("id")
    log("  [%s] low-confidence match, skipped: %r -> %r (score %s)"
        % (source, name, best.get("name"), best.get("score")))
    return None


def resolve_names(names, source):
    mbids = set()
    for name in sorted(names):
        mbid = resolve_name_to_mbid(name, source)
        if mbid:
            mbids.add(mbid)
        time.sleep(1.1)  # be a good citizen of MusicBrainz's rate limit
    log("%s: %d/%d names resolved to MusicBrainz IDs" % (source, len(mbids), len(names)))
    return mbids


# ---------------------------------------------------------------- Label roster
def label_artists():
    releases, offset = [], 0
    while True:
        d = mb_get("release?label=%s&inc=artist-credits&fmt=json&limit=100&offset=%d"
                   % (LABEL_MBID, offset))
        if not d:
            break
        batch = d.get("releases", [])
        releases.extend(batch)
        total = d.get("release-count", 0)
        offset += len(batch)
        if offset >= total or not batch:
            break
        time.sleep(1.1)

    counts = {}
    for r in releases:
        for ac in r.get("artist-credit", []):
            a = ac.get("artist") or {}
            mbid = a.get("id")
            if not mbid or mbid == VARIOUS_ARTISTS_MBID:
                continue
            counts[mbid] = counts.get(mbid, 0) + 1

    mbids = {m for m, n in counts.items() if n >= MIN_RELEASES}
    log("label roster: %d releases scanned, %d artists" % (len(releases), len(mbids)))
    return mbids


# ------------------------------------------------------------- RTE radio show
RTE_ARTICLE_RE = re.compile(
    r'<article class="playlist">.*?<h3>(.*?)</h3>\s*'
    r'<p class=[\'"]artist[\'"]>(.*?)</p>',
    re.S,
)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s).strip()
    return s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')


def rte_episode_ids():
    url = "https://www.rte.ie/radio/%s/%s/episodes/json/?page=1" % (RTE_STATION, RTE_SHOW)
    d = json.loads(http_get(url))
    return [p["id"] for p in d.get("programmes", [])[:RTE_EPISODES_PER_RUN]]


def rte_artist_names():
    names = set()
    for ep_id in rte_episode_ids():
        url = "https://www.rte.ie/radio/%s/%s/episodes/%s/" % (RTE_STATION, RTE_SHOW, ep_id)
        html = http_get(url)
        for _title, artist in RTE_ARTICLE_RE.findall(html):
            artist = strip_tags(artist)
            if artist:
                names.add(artist)
        time.sleep(0.5)
    log("rte show: %d episodes, %d distinct artist names" % (RTE_EPISODES_PER_RUN, len(names)))
    return names


# ------------------------------------------------------------------ BBC radio show
BBC_ARTIST_RE = re.compile(
    r'segments-list__item--music.*?<span class="artist">(.*?)</span>',
    re.S,
)


def bbc_episode_pids():
    html = http_get("https://www.bbc.co.uk/programmes/%s/episodes" % BBC_SHOW_PID)
    return sorted(set(re.findall(r"programmes/(m[0-9a-z]{7})", html)))


def bbc_artist_names():
    names = set()
    pids = bbc_episode_pids()
    for pid in pids:
        html = http_get("https://www.bbc.co.uk/programmes/%s" % pid)
        for artist in BBC_ARTIST_RE.findall(html):
            artist = strip_tags(artist)
            if artist:
                names.add(artist)
        time.sleep(0.5)
    log("bbc show: %d episodes, %d distinct artist names" % (len(pids), len(names)))
    return names


def main():
    label = label_artists()
    rte = resolve_names(rte_artist_names(), "rte show")
    bbc = resolve_names(bbc_artist_names(), "bbc show")
    combined = sorted(label | rte | bbc)
    log("combined total: %d artists (label %d, rte show %d, bbc show %d)"
        % (len(combined), len(label), len(rte), len(bbc)))

    payload = [{"MusicBrainzId": m} for m in combined]
    with open(OUT_PATH, "w") as fh:
        json.dump(payload, fh, indent=1)
    log("wrote %s" % OUT_PATH)


if __name__ == "__main__":
    sys.exit(main())
