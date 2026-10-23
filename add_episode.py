#!/usr/bin/env python3
"""Add one episode by YouTube URL, then rebuild index.html.

    ./add_episode.py https://www.youtube.com/watch?v=XXXXXXXXXXX
    ./add_episode.py --gui
"""

import argparse
import sys

import build
import synapse_youtube as youtube


class AddEpisodeError(Exception):
    pass


def add_episode(url, number=None, force=False, fetch_video=youtube.fetch_video):
    """Fetch metadata, add the episode, save and rebuild. Returns (episode, renumbered).

    Without an explicit number the episode is placed by air date and the list is
    renumbered 1..N, so later episodes move up by one; renumbered maps youtube_id -> (old, new).
    """
    video_id = youtube.extract_video_id(url)
    episodes = build.load_episodes()
    if any(episode["youtube_id"] == video_id for episode in episodes):
        raise AddEpisodeError(f"{video_id} is already listed")

    metadata = fetch_video(video_id)
    if not force and not youtube.is_project_synapse_video(metadata["title"], metadata.get("description")):
        raise AddEpisodeError(
            f"{metadata['title']!r} does not look like a new Project Synapse episode: the show isn't "
            "named in its title or description, or it is a replay/encore/cross-post (use --force)"
        )

    renumbered = {}
    if number is None:
        episode = youtube.episode_from_metadata(metadata, max((existing["number"] for existing in episodes), default=0) + 1)
        episodes.append(episode)
        renumbered = build.renumber_chronologically(episodes)
        renumbered.pop(episode["youtube_id"], None)
    elif any(episode["number"] == number for episode in episodes):
        raise AddEpisodeError(f"episode number {number} is already taken")
    else:
        episode = youtube.episode_from_metadata(metadata, number)
        episodes.append(episode)

    build.save_episodes(episodes)
    build.build()
    return episode, renumbered


def describe(episode, renumbered):
    text = f"Added Ep {episode['number']} ({episode['date']}): {episode['title']}"
    if renumbered:
        text += f"; renumbered {len(renumbered)} other episodes"
    return text


def run_gui():
    import tkinter as tk

    window = tk.Tk()
    window.title("Add Project Synapse episode")
    tk.Label(window, text="YouTube URL:").grid(row=0, column=0, padx=6, pady=6)
    url_entry = tk.Entry(window, width=50)
    url_entry.grid(row=0, column=1, padx=6, pady=6)
    status = tk.Label(window, text="", wraplength=420, justify="left")
    status.grid(row=2, column=0, columnspan=2, padx=6, pady=6)

    def on_add():
        status.config(text="Fetching…")
        window.update_idletasks()
        try:
            status.config(text=describe(*add_episode(url_entry.get())))
        except (AddEpisodeError, ValueError, youtube.YouTubeError, build.EpisodeDataError) as error:
            status.config(text=f"Error: {error}")

    tk.Button(window, text="Add", command=on_add).grid(row=1, column=1, sticky="e", padx=6)
    window.mainloop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add a Project Synapse episode by YouTube URL.")
    parser.add_argument("url", nargs="?", help="YouTube watch/share URL or bare video id")
    parser.add_argument("--number", type=int,
                        help="episode number (default: place by air date and renumber later episodes)")
    parser.add_argument("--force", action="store_true",
                        help="add even if neither title nor description names Project Synapse")
    parser.add_argument("--gui", action="store_true", help="open a small Tk window instead")
    args = parser.parse_args(argv)

    if args.gui:
        return run_gui()
    if not args.url:
        parser.error("a URL is required unless --gui is given")
    try:
        print(describe(*add_episode(args.url, number=args.number, force=args.force)))
    except (AddEpisodeError, ValueError, youtube.YouTubeError, build.EpisodeDataError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
