#!/usr/bin/env python3
"""Accumulate Project Synapse audio from Libsyn and render podcast.xml."""

import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent
EPISODES_PATH = ROOT / "podcast_episodes.json"
OUTPUT_PATH = ROOT / "podcast.xml"
SOURCE_URL = "https://hashtagtrending.libsyn.com/rss"
# Libsyn's path-based archive search supplies original RSS metadata, unlike its HTML pages.
BACKFILL_URL = "https://hashtagtrending.libsyn.com/rss/size/200/search/Project%20Synapse"
BACKFILL_LIMIT = 200
SITE_URL = "https://projectsynapse.ca/"
FEED_URL = SITE_URL + "podcast.xml"
COVER_ART_URL = SITE_URL + "podcast-cover.jpg"  # TODO: supply a 1400–3000px square JPG/PNG.
OWNER_NAME = "Jim Love, Marcel Gagné, John Pinard"
OWNER_EMAIL = ""  # TODO: set a real owner email; omit itunes:email until supplied.
CHANNEL_DESCRIPTION = (
    "A weekly deep dive into artificial intelligence — what it means, where it's going, "
    "and why it matters. With Jim Love, Marcel Gagné and John Pinard."
)
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
ITUNES = "{" + ITUNES_NAMESPACE + "}"
TEXT_FIELDS = ("title", "description", "pubDate", "guid", "link")


def publication_time(episode):
    published = parsedate_to_datetime(episode["pubDate"])
    if published.tzinfo is None:
        raise ValueError(f"pubDate has no timezone for {episode['guid']}")
    return published


def validate_episode(episode):
    for field in (*TEXT_FIELDS, "duration"):
        if not isinstance(episode[field], str) or (field != "description" and not episode[field]):
            raise ValueError(f"missing or invalid {field} in podcast episode")
    publication_time(episode)
    enclosure = episode["enclosure"]
    for field in ("url", "length", "type"):
        if not isinstance(enclosure[field], str) or not enclosure[field]:
            raise ValueError(f"missing enclosure {field} for {episode['guid']}")
    if not enclosure["length"].isdigit() or int(enclosure["length"]) <= 0:
        raise ValueError(f"invalid enclosure length for {episode['guid']}")
    if not enclosure["type"].startswith(("audio/", "video/")):
        raise ValueError(f"non-media enclosure for {episode['guid']}")
    if not isinstance(episode["guid_attributes"], dict):
        raise ValueError(f"invalid guid attributes for {episode['guid']}")


def parse_episodes(xml):
    """Preserve source values (including HTML descriptions and enclosure URLs)."""
    root = ElementTree.fromstring(xml)
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Libsyn response is not an RSS channel")
    episodes = {}
    for item in channel.findall("item"):
        if "project synapse" not in item.findtext("title", "").casefold():
            continue
        episode = {field: item.findtext(field, "") for field in TEXT_FIELDS}
        guid = item.find("guid")
        enclosure = item.find("enclosure")
        if guid is None or enclosure is None:
            raise ValueError(f"missing guid or enclosure for {episode['title']}")
        episode["guid_attributes"] = dict(guid.attrib)
        episode["enclosure"] = dict(enclosure.attrib)
        episode["duration"] = item.findtext(f"{ITUNES}duration", "")
        validate_episode(episode)
        episodes[episode["guid"]] = episode
    return episodes


def load_episodes(path=EPISODES_PATH):
    path = Path(path)
    if not path.exists():
        return {}
    episodes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(episodes, dict):
        raise ValueError("podcast episode data must be keyed by guid")
    for guid, episode in episodes.items():
        validate_episode(episode)
        if guid != episode["guid"]:
            raise ValueError(f"podcast key does not match guid: {guid}")
    return episodes


def merge_episodes(stored, incoming):
    """Refresh matching GUIDs and retain every previously stored episode."""
    return {**stored, **incoming}


def attributes(values):
    return "".join(f" {name}={quoteattr(value)}" for name, value in sorted(values.items()))


def render_item(episode):
    lines = ["    <item>"]
    for field in TEXT_FIELDS:
        attrs = attributes(episode["guid_attributes"]) if field == "guid" else ""
        lines.append(f"      <{field}{attrs}>{escape(episode[field])}</{field}>")
    lines.extend([
        f"      <enclosure{attributes(episode['enclosure'])} />",
        f"      <itunes:duration>{escape(episode['duration'])}</itunes:duration>",
        "      <itunes:episodeType>full</itunes:episodeType>",
        "    </item>",
    ])
    return "\n".join(lines) + "\n"


def render_feed(episodes):
    # GUID breaks equal-date ties; no build timestamp or input ordering enters the output.
    ordered = sorted(episodes.values(), key=lambda episode: (
        publication_time(episode), episode["guid"]
    ), reverse=True)
    owner_email = f"      <itunes:email>{escape(OWNER_EMAIL)}</itunes:email>\n" if OWNER_EMAIL else ""
    last_build = f"    <lastBuildDate>{escape(ordered[0]['pubDate'])}</lastBuildDate>\n" if ordered else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rss version="2.0" xmlns:itunes="{ITUNES_NAMESPACE}" '
        f'xmlns:podcast="{PODCAST_NAMESPACE}" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Project Synapse</title>\n"
        f"    <link>{SITE_URL}</link>\n"
        f"    <description>{escape(CHANNEL_DESCRIPTION)}</description>\n"
        "    <language>en-ca</language>\n"
        f"    <itunes:author>{escape(OWNER_NAME)}</itunes:author>\n"
        "    <itunes:owner>\n"
        f"      <itunes:name>{escape(OWNER_NAME)}</itunes:name>\n"
        f"{owner_email}"
        "    </itunes:owner>\n"
        '    <itunes:category text="Technology" />\n'
        "    <itunes:explicit>false</itunes:explicit>\n"
        "    <itunes:type>episodic</itunes:type>\n"
        f"    <itunes:image href={quoteattr(COVER_ART_URL)} />\n"
        f'    <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml" />\n'
        f"{last_build}"
        + "".join(render_item(episode) for episode in ordered)
        + "  </channel>\n</rss>\n"
    )


def fetch_feed(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def refresh(episodes_path=EPISODES_PATH, output_path=OUTPUT_PATH, *, backfill=False):
    episodes = load_episodes(episodes_path)
    previous_count = len(episodes)
    if backfill:
        archive_xml = fetch_feed(BACKFILL_URL)
        if len(ElementTree.fromstring(archive_xml).findall("channel/item")) >= BACKFILL_LIMIT:
            raise ValueError("archive hit its item limit; investigate before importing a partial backfill")
        episodes = merge_episodes(episodes, parse_episodes(archive_xml))
    # Prefer the standard RSS values when the archive and current feed overlap.
    episodes = merge_episodes(episodes, parse_episodes(fetch_feed(SOURCE_URL)))
    rendered = render_feed(episodes)
    ElementTree.fromstring(rendered)
    data = json.dumps(episodes, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # All fetching, validation and rendering precede writes, so network failure changes neither file.
    Path(episodes_path).write_text(data, encoding="utf-8")
    Path(output_path).write_text(rendered, encoding="utf-8")
    return len(episodes), len(episodes) - previous_count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true", help="also import Libsyn's archive RSS once")
    args = parser.parse_args(argv)
    try:
        count, added = refresh(backfill=args.backfill)
    except (OSError, urllib.error.URLError, ValueError, KeyError, ElementTree.ParseError) as error:
        print(f"Podcast refresh failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {OUTPUT_PATH.name} with {count} audio episodes ({added} added)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
