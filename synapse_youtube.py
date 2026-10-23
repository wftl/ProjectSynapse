"""YouTube helpers shared by update.py and add_episode.py (yt-dlp + RSS)."""

import json
import os
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

YT_DLP = os.environ.get("YT_DLP", "/usr/bin/yt-dlp")
CHANNEL_URL = "https://www.youtube.com/@technewsday"
SEARCH_URL = CHANNEL_URL + "/search?query=Project%20Synapse"
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
# The show is recorded in Ontario; upload timestamps late in the evening would
# otherwise land on the next day in UTC.
SHOW_TIMEZONE = ZoneInfo("America/Toronto")

IGNORED_IDS_PATH = Path(__file__).resolve().parent / "ignored_ids.txt"
MAX_BLURB_CHARS = 600
PARAGRAPH_MIN_CHARS = 200
SUBPROCESS_TIMEOUT_SECONDS = 300

SHOW_NAME = "Project Synapse"
# \s* so the #ProjectSynapse hashtag in descriptions counts as a mention.
_SHOW_NAME_RE = re.compile(r"project\s*synapse", re.IGNORECASE)
# Re-uploads of an existing episode, not new episodes.
_RERUN_RE = re.compile(r"\b(replay|encore|rerun|re-run)\b", re.IGNORECASE)
# Episodes re-published under the Cybersecurity Today show name.
_CROSS_POST_RE = re.compile(r"cyber\s*security\s+today", re.IGNORECASE)
# The show name at either end of a title, with whatever separator joins it to the rest.
_LEADING_SHOW_NAME_RE = re.compile(r"^project\s*synapse\b[\s:|\-–—]*", re.IGNORECASE)
_TRAILING_SHOW_NAME_RE = re.compile(r"[\s:|&\-–—]*\(?\s*project\s*synapse\s*\)?$", re.IGNORECASE)
_TITLE_EDGE_PUNCTUATION = " :|&-–—"
_VIDEO_ID_RE = re.compile(
    r"(?:youtu\.be/|[?&]v=|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Description sentences that are promos, links or chapter markers rather than a summary.
_LINK_RE = re.compile(
    r"https?://|www\.|discord|\b[\w-]+\.(?:com|ca|org|net|io|ai|gg|ly|tv)\b(?:/\S*)?",
    re.IGNORECASE,
)
# Sponsor reads ("Hashtag Trending would like to thank Meter for their support...",
# "This episode is brought to you by NordLayer... use the discount code...").
# The lookbehind keeps "state-sponsored" prose.
_SPONSOR_RE = re.compile(
    r"\bthanks?\b[^.]{0,60}\bfor (?:their |its |the )?support|brought to you by|"
    r"(?<![\w-])sponsor(?:s|ship|ed by)?\b|\b(?:promo|discount|coupon) code|"
    r"\buse (?:the )?code\b|\d+% off\b|buymeacoffee",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    _LINK_RE.pattern + "|" + _SPONSOR_RE.pattern
    + r"|links mentioned|subscribe|^\s*#|^\s*\d{1,2}:\d{2}",
    re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r"[.!?…][\"'”’)]*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’)])\s+")

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


class YouTubeError(RuntimeError):
    pass


def mentions_project_synapse(text):
    return bool(_SHOW_NAME_RE.search(text or ""))


def is_rerun_or_cross_post(title, description=""):
    return bool(
        _RERUN_RE.search(title) or _RERUN_RE.search(description or "") or _CROSS_POST_RE.search(title)
    )


def is_project_synapse_video(title, description=""):
    """True for a new episode: the show is named in the title or description, and it isn't a re-run."""
    mentioned = mentions_project_synapse(title) or mentions_project_synapse(description)
    return mentioned and not is_rerun_or_cross_post(title, description)


def format_title(title):
    """Give every title the "Project Synapse: <title>" form.

    A show name at the start or end ("X | Project Synapse", "Project Synapse - X")
    is moved to the prefix. A title naming the show mid-sentence is left alone,
    since prefixing it would repeat the name.
    """
    title = " ".join(title.split())
    rest = _LEADING_SHOW_NAME_RE.sub("", title, count=1)
    rest = _TRAILING_SHOW_NAME_RE.sub("", rest, count=1).strip(_TITLE_EDGE_PUNCTUATION)
    if not rest:
        return SHOW_NAME
    if mentions_project_synapse(rest):
        return title
    return f"{SHOW_NAME}: {rest}"


def extract_video_id(url_or_id):
    text = url_or_id.strip()
    if _BARE_ID_RE.match(text):
        return text
    match = _VIDEO_ID_RE.search(text)
    if not match:
        raise ValueError(f"could not find a YouTube video id in {url_or_id!r}")
    return match.group(1)


def trim_description(description, max_chars=MAX_BLURB_CHARS):
    """Turn a YouTube description into a one-paragraph blurb.

    Drops sponsor reads, promo/link sentences and headline-style lines (no closing
    punctuation), then keeps whole sentences up to max_chars.
    """
    prose, fallback = [], []
    for line in description.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        # Short lines with a link are link lists ("Check out X: https://..."); drop them
        # whole. Everything else is filtered per sentence, since a sponsor mention can
        # sit inside good prose.
        if len(line) < PARAGRAPH_MIN_CHARS and _LINK_RE.search(line):
            continue
        all_sentences = _SENTENCE_SPLIT_RE.split(line)
        # A line that opens with a sponsor read is ad copy throughout
        # ("Meter delivers a complete networking stack..."), so drop all of it.
        if _SPONSOR_RE.search(all_sentences[0]):
            continue
        sentences = [s for s in all_sentences if not _NOISE_RE.search(s)]
        fallback.extend(sentences)
        prose.extend(s for s in sentences if _SENTENCE_END_RE.search(s))
    sentences = prose or fallback
    text = " ".join(sentences)
    if len(text) <= max_chars:
        return text

    blurb = ""
    for sentence in sentences:
        candidate = f"{blurb} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        blurb = candidate
    if blurb:
        return blurb
    # A single enormous sentence: cut at a word boundary.
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def show_date(metadata):
    """ISO date of publication in the show's timezone."""
    timestamp = metadata.get("timestamp") or metadata.get("release_timestamp")
    if timestamp:
        published = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(SHOW_TIMEZONE)
        return published.date().isoformat()
    upload_date = metadata.get("upload_date")
    if not upload_date:
        raise YouTubeError(f"no publication date for video {metadata.get('id')}")
    return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"


def episode_from_metadata(metadata, number):
    return {
        "number": number,
        "title": format_title(metadata["title"]),
        "date": show_date(metadata),
        "youtube_id": metadata["id"],
        "blurb": trim_description(metadata.get("description") or ""),
    }


def run_yt_dlp(args):
    command = [YT_DLP, "--no-update", "--no-warnings", *args]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise YouTubeError(f"yt-dlp failed to run: {error}") from error
    if result.returncode != 0:
        raise YouTubeError(f"yt-dlp exited {result.returncode}: {result.stderr.strip()[-500:]}")
    return result.stdout


def fetch_video(url_or_id):
    video_id = extract_video_id(url_or_id)
    output = run_yt_dlp(["--skip-download", "-J", f"https://www.youtube.com/watch?v={video_id}"])
    return json.loads(output)


def resolve_channel_id(channel_url=CHANNEL_URL):
    output = run_yt_dlp(["-J", "--flat-playlist", "--playlist-items", "0", channel_url])
    channel_id = json.loads(output).get("channel_id")
    if not channel_id:
        raise YouTubeError(f"yt-dlp returned no channel_id for {channel_url}")
    return channel_id


def listing(video_id, title, description=None, duration=None):
    """What a channel listing tells us about a video before fetching it.

    description and duration are None when the source doesn't provide them
    (search results carry a description snippet, channel tabs a duration, RSS
    the full description).
    """
    return {"id": video_id, "title": title or "", "description": description, "duration": duration}


def list_playlist(url, limit):
    """Listings from a channel tab or search page, without per-video requests."""
    output = run_yt_dlp(["--flat-playlist", "--playlist-end", str(limit), "-J", url])
    entries = json.loads(output).get("entries") or []
    # Search results can include playlists; keep only plain videos.
    return [
        listing(entry["id"], entry.get("title"), entry.get("description"), entry.get("duration"))
        for entry in entries
        if entry.get("id") and _BARE_ID_RE.match(entry["id"])
    ]


def parse_rss(xml_text):
    root = ElementTree.fromstring(xml_text)
    videos = []
    for entry in root.findall("atom:entry", ATOM_NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ATOM_NS)
        title = entry.findtext("atom:title", default="", namespaces=ATOM_NS)
        description = entry.findtext("media:group/media:description", namespaces=ATOM_NS)
        if video_id:
            videos.append(listing(video_id, title, description))
    return videos


def fetch_rss(channel_id):
    """The feed only holds the latest ~15 uploads, so it is a fast first look, not a full source."""
    url = RSS_URL.format(channel_id=channel_id)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return parse_rss(response.read())
    except (OSError, ElementTree.ParseError) as error:
        raise YouTubeError(f"RSS fetch failed: {error}") from error


def load_ignored_ids(path=IGNORED_IDS_PATH):
    """Videos that look like episodes but are not (one id per line, # comments)."""
    if not Path(path).exists():
        return set()
    ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids
