#!/usr/bin/env python3
"""Find new Project Synapse episodes on @technewsday, add them, and rebuild index.html.

Only videos whose title or description mentions "Project Synapse" (and that
aren't replays, encores or Cybersecurity Today cross-posts) and that were
published after the newest listed episode are added, numbered on from the
highest episode in publication order. Older unlisted videos are reported but left
alone: inserting one renumbers every later episode, which needs a human
check, so add them with add_episode.py instead.
"""

import argparse
import sys

import build
import synapse_youtube as youtube

SEARCH_LIMIT = 40
RECENT_UPLOADS_LIMIT = 80
# Episodes run about an hour (the shortest is 48 minutes) and the daily shows
# 5-20 minutes, so a short listing that doesn't name the show isn't worth fetching.
MIN_EPISODE_SECONDS = 40 * 60


def discover_candidates(channel_id, log):
    """{video_id: listing} merged from every source that answers. Raises if none do."""
    sources = [
        ("RSS feed", lambda: youtube.fetch_rss(channel_id)),
        ("channel search", lambda: youtube.list_playlist(youtube.SEARCH_URL, SEARCH_LIMIT)),
        ("recent uploads", lambda: youtube.list_playlist(youtube.CHANNEL_URL + "/videos", RECENT_UPLOADS_LIMIT)),
        ("recent streams", lambda: youtube.list_playlist(youtube.CHANNEL_URL + "/streams", SEARCH_LIMIT)),
    ]
    found, failures = {}, 0
    for name, fetch in sources:
        try:
            videos = fetch()
        except youtube.YouTubeError as error:
            failures += 1
            log(f"warning: {name} unavailable: {error}")
            continue
        log(f"{name}: {len(videos)} videos")
        for video in videos:
            merged = found.setdefault(video["id"], dict(video))
            # Sources know different things (RSS: description, channel tabs: duration).
            for key, value in video.items():
                if merged.get(key) is None:
                    merged[key] = value
    if failures == len(sources):
        raise youtube.YouTubeError("every discovery source failed")
    return found


def worth_fetching(listing):
    """Whether a listing could be a new episode, judged without fetching its metadata."""
    if youtube.is_rerun_or_cross_post(listing["title"]):
        return False
    if youtube.mentions_project_synapse(listing["title"]) or youtube.mentions_project_synapse(listing["description"]):
        return True
    # Channel tabs give no description, so a long video might still name the show in its own.
    return listing["duration"] is None or listing["duration"] >= MIN_EPISODE_SECONDS


def select_new_episodes(candidates, episodes, ignored_ids, fetch_video, log):
    """Fetch full metadata for promising candidates and return new episode dicts, numbered."""
    listed_ids = {episode["youtube_id"] for episode in episodes}
    # max + 1 only continues the sequence if the list is already numbered by air date.
    for problem in build.numbering_problems(episodes):
        log(f"warning: {problem}; new episodes may be misnumbered")
    newest_date = max(episode["date"] for episode in episodes)
    next_number = max(episode["number"] for episode in episodes) + 1

    accepted = []
    for video_id, listing in candidates.items():
        if video_id in listed_ids or video_id in ignored_ids:
            continue
        if not worth_fetching(listing):
            continue
        metadata = fetch_video(video_id)
        # Flat listings carry stale titles and truncated descriptions; verify against the real ones.
        if not youtube.is_project_synapse_video(metadata["title"], metadata.get("description")):
            log(f"skip {video_id}: {metadata['title']!r} is not a new Project Synapse episode "
                "(show not named, or a replay/encore/cross-post)")
            continue
        published = youtube.show_date(metadata)
        if published <= newest_date:
            log(f"skip {video_id} ({published}): not newer than the newest listed episode; "
                "if genuine, add it with add_episode.py (renumbers later episodes)")
            continue
        accepted.append(metadata)

    accepted.sort(key=lambda metadata: (youtube.show_date(metadata), metadata.get("timestamp") or 0))
    return [
        youtube.episode_from_metadata(metadata, next_number + offset)
        for offset, metadata in enumerate(accepted)
    ]


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report new episodes without writing files")
    parser.add_argument("--channel-id", help="skip resolving the @technewsday channel id")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    log = lambda message: print(message, file=sys.stderr)

    try:
        channel_id = args.channel_id or youtube.resolve_channel_id()
        log(f"channel id: {channel_id}")
        episodes = build.load_episodes()
        candidates = discover_candidates(channel_id, log)
        new_episodes = select_new_episodes(
            candidates, episodes, youtube.load_ignored_ids(), youtube.fetch_video, log
        )
    except (youtube.YouTubeError, build.EpisodeDataError) as error:
        log(f"error: {error}")
        return 1

    if not new_episodes:
        print("No new episodes.")
        return 0
    for episode in new_episodes:
        print(f"Ep {episode['number']}  {episode['date']}  {episode['youtube_id']}  {episode['title']}")
    if args.dry_run:
        print("(dry run: nothing written)")
        return 0

    build.save_episodes(episodes + new_episodes)
    count = build.build()
    print(f"Added {len(new_episodes)}; index.html now lists {count} episodes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
