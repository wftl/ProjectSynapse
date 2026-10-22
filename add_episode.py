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
    """Fetch metadata, append the episode, save and rebuild. Returns the new episode."""
    video_id = youtube.extract_video_id(url)
    episodes = build.load_episodes()
    if any(episode["youtube_id"] == video_id for episode in episodes):
        raise AddEpisodeError(f"{video_id} is already listed")

    metadata = fetch_video(video_id)
    if not force and not youtube.is_project_synapse_title(metadata["title"]):
        raise AddEpisodeError(
            f"title {metadata['title']!r} does not look like a Project Synapse episode (use --force)"
        )

    if number is None:
        number = max((episode["number"] for episode in episodes), default=0) + 1
    elif any(episode["number"] == number for episode in episodes):
        raise AddEpisodeError(f"episode number {number} is already taken")

    episode = youtube.episode_from_metadata(metadata, number)
    build.save_episodes(episodes + [episode])
    build.build()
    return episode


def describe(episode):
    return f"Added Ep {episode['number']} ({episode['date']}): {episode['title']}"


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
            status.config(text=describe(add_episode(url_entry.get())))
        except (AddEpisodeError, ValueError, youtube.YouTubeError, build.EpisodeDataError) as error:
            status.config(text=f"Error: {error}")

    tk.Button(window, text="Add", command=on_add).grid(row=1, column=1, sticky="e", padx=6)
    window.mainloop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add a Project Synapse episode by YouTube URL.")
    parser.add_argument("url", nargs="?", help="YouTube watch/share URL or bare video id")
    parser.add_argument("--number", type=int, help="episode number (default: highest + 1)")
    parser.add_argument("--force", action="store_true", help="add even if the title lacks 'Project Synapse'")
    parser.add_argument("--gui", action="store_true", help="open a small Tk window instead")
    args = parser.parse_args(argv)

    if args.gui:
        return run_gui()
    if not args.url:
        parser.error("a URL is required unless --gui is given")
    try:
        print(describe(add_episode(args.url, number=args.number, force=args.force)))
    except (AddEpisodeError, ValueError, youtube.YouTubeError, build.EpisodeDataError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
