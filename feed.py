"""Render the RSS 2.0 feed of episodes (feed.xml), used by build.py."""

import re
from datetime import date, datetime, time, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

SITE_URL = "https://projectsynapse.ca/"
FEED_URL = SITE_URL + "feed.xml"
CHANNEL_TITLE = "Project Synapse"
CHANNEL_DESCRIPTION = (
    "A weekly deep dive into artificial intelligence — what it means, where it's going, "
    "and why it matters. With Jim Love, Marcel Gagné and John Pinard."
)

# Characters XML 1.0 forbids even when escaped; YouTube descriptions occasionally carry them.
INVALID_XML_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

# Episodes only have a date. Noon UTC falls on that same calendar day across North
# America, so readers in Toronto don't see an episode dated the evening before.
PUBLISH_TIME = time(12, 0, tzinfo=timezone.utc)


def xml_text(text):
    return escape(INVALID_XML_CHARS_RE.sub("", text))


def rfc822_date(iso_date):
    # format_datetime always uses English day/month names, unlike locale-dependent strftime.
    return format_datetime(datetime.combine(date.fromisoformat(iso_date), PUBLISH_TIME))


def render_item(episode):
    youtube_id = episode["youtube_id"]
    thumbnail_url = f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg"
    return (
        "    <item>\n"
        f"      <title>{xml_text(episode['title'])}</title>\n"
        f"      <link>https://www.youtube.com/watch?v={youtube_id}</link>\n"
        f'      <guid isPermaLink="false">yt:video:{youtube_id}</guid>\n'
        f"      <pubDate>{rfc822_date(episode['date'])}</pubDate>\n"
        f"      <description>{xml_text(episode['blurb'])}</description>\n"
        # hqdefault exists for every video; maxresdefault (used on the page) sometimes doesn't.
        f'      <media:thumbnail url={quoteattr(thumbnail_url)} width="480" height="360" />\n'
        "    </item>\n"
    )


def render_feed(episodes):
    """The whole feed as a string. Depends only on the episodes, so rebuilding unchanged
    data produces identical output (lastBuildDate is the newest episode's date, not now)."""
    ordered = sorted(episodes, key=lambda episode: episode["number"], reverse=True)
    newest_date = max(episode["date"] for episode in episodes)
    items = "".join(render_item(episode) for episode in ordered)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/">\n'
        "  <channel>\n"
        f"    <title>{xml_text(CHANNEL_TITLE)}</title>\n"
        f"    <link>{SITE_URL}</link>\n"
        f"    <description>{xml_text(CHANNEL_DESCRIPTION)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{rfc822_date(newest_date)}</lastBuildDate>\n"
        f'    <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml" />\n'
        f"{items}"
        "  </channel>\n"
        "</rss>\n"
    )
