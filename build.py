#!/usr/bin/env python3
"""Regenerate index.html from episodes.json and the templates/ directory."""

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES_PATH = ROOT / "episodes.json"
OUTPUT_PATH = ROOT / "index.html"
PAGE_TEMPLATE_PATH = ROOT / "templates" / "page.html"
CARD_TEMPLATE_PATH = ROOT / "templates" / "card.html"

REQUIRED_FIELDS = ("number", "title", "date", "youtube_id", "blurb")
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")

# Blurbs this short fit inside the 4-line clamp, so a "Read more" button would do nothing.
SHORT_BLURB_CHARS = 200
TOGGLE_BUTTON_HTML = '        <button class="toggle-btn" onclick="toggleDesc(this)">Read more</button>\n'


class EpisodeDataError(ValueError):
    pass


def load_episodes(path=EPISODES_PATH):
    episodes = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_episodes(episodes)
    return episodes


def save_episodes(episodes, path=EPISODES_PATH):
    validate_episodes(episodes)
    ordered = sorted(episodes, key=lambda episode: episode["number"], reverse=True)
    text = json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def validate_episodes(episodes):
    seen_numbers, seen_ids = set(), set()
    for episode in episodes:
        missing = [field for field in REQUIRED_FIELDS if field not in episode]
        if missing:
            raise EpisodeDataError(f"episode {episode!r} is missing {missing}")
        if not isinstance(episode["number"], int) or episode["number"] < 1:
            raise EpisodeDataError(f"bad episode number: {episode['number']!r}")
        # The id is interpolated into URLs, so it must be strictly well-formed.
        if not YOUTUBE_ID_RE.match(episode["youtube_id"]):
            raise EpisodeDataError(f"bad YouTube id: {episode['youtube_id']!r}")
        date.fromisoformat(episode["date"])
        if episode["number"] in seen_numbers:
            raise EpisodeDataError(f"duplicate episode number {episode['number']}")
        if episode["youtube_id"] in seen_ids:
            raise EpisodeDataError(f"duplicate YouTube id {episode['youtube_id']}")
        seen_numbers.add(episode["number"])
        seen_ids.add(episode["youtube_id"])


def renumber_chronologically(episodes):
    """Number episodes 1..N by air date, in place. Returns {youtube_id: (old, new)} for moved ones.

    Same-day ties keep their existing relative order, so a newly appended
    episode (numbered highest) lands after an existing one from that day.
    """
    ordered = sorted(episodes, key=lambda episode: (episode["date"], episode["number"]))
    changes = {}
    for new_number, episode in enumerate(ordered, start=1):
        if episode["number"] != new_number:
            changes[episode["youtube_id"]] = (episode["number"], new_number)
            episode["number"] = new_number
    return changes


def numbering_problems(episodes):
    """Ways the numbering differs from 1..N in air-date order (empty if it matches)."""
    ordered = sorted(episodes, key=lambda episode: episode["number"])
    problems = []
    for expected, episode in enumerate(ordered, start=1):
        if episode["number"] != expected:
            problems.append(f"episode numbers skip from {expected - 1} to {episode['number']}")
            break
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier["date"] > later["date"]:
            problems.append(
                f"Ep {earlier['number']} ({earlier['date']}) is dated after Ep {later['number']} ({later['date']})"
            )
    return problems


def format_display_date(iso_date):
    parsed = date.fromisoformat(iso_date)
    return f"{parsed:%B} {parsed.day}, {parsed.year}"


def fill_template(template, values):
    # Single pass, so text containing "{{...}}" from YouTube is never re-expanded.
    def substitute(match):
        name = match.group(1)
        if name not in values:
            raise KeyError(f"template placeholder {{{{{name}}}}} has no value")
        return values[name]

    return PLACEHOLDER_RE.sub(substitute, template)


def render_card(episode, card_template):
    return fill_template(card_template, {
        "NUMBER": str(episode["number"]),
        "YOUTUBE_ID": episode["youtube_id"],
        "DATE": format_display_date(episode["date"]),
        "TITLE": html.escape(episode["title"], quote=False),
        "BLURB": html.escape(episode["blurb"], quote=False),
        "TOGGLE_BUTTON": "" if len(episode["blurb"]) < SHORT_BLURB_CHARS else TOGGLE_BUTTON_HTML,
    })


def year_range(episodes):
    years = sorted(date.fromisoformat(episode["date"]).year for episode in episodes)
    if years[0] == years[-1]:
        return str(years[0])
    return f"{years[0]}–{years[-1]}"


def render_page(episodes, page_template, card_template):
    ordered = sorted(episodes, key=lambda episode: episode["number"], reverse=True)
    cards = "".join(render_card(episode, card_template) for episode in ordered)
    return fill_template(page_template, {
        "EPISODE_COUNT": str(len(episodes)),
        "YEAR_RANGE": year_range(episodes),
        "EPISODE_CARDS": cards,
    })


def build(episodes_path=EPISODES_PATH, output_path=OUTPUT_PATH):
    episodes = load_episodes(episodes_path)
    page = render_page(
        episodes,
        PAGE_TEMPLATE_PATH.read_text(encoding="utf-8"),
        CARD_TEMPLATE_PATH.read_text(encoding="utf-8"),
    )
    Path(output_path).write_text(page, encoding="utf-8")
    return len(episodes)


def main():
    count = build()
    print(f"Wrote {OUTPUT_PATH.name} with {count} episodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
