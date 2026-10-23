# Project Synapse episode archive

A static page (`index.html`) listing every episode of Project Synapse from the
[@technewsday](https://www.youtube.com/@technewsday) YouTube channel.

## Generating the page

`index.html` is generated, so don't edit it by hand. Episode data lives in
`episodes.json`, and the markup lives in `templates/page.html` and `templates/card.html`.

```sh
./build.py                 # regenerate index.html from episodes.json
```

Each episode in `episodes.json` has `number`, `title`, `date` (ISO `YYYY-MM-DD`),
`youtube_id` and `blurb` (plain text; `build.py` HTML-escapes it). The episode
count and year range in the stats bar come from the data. Cards with a blurb under
200 characters get no "Read more" button.

## Adding episodes

```sh
./update.py --dry-run      # list new episodes without writing anything
./update.py                # add them and rebuild
./add_episode.py https://www.youtube.com/watch?v=VIDEO_ID   # add one by URL
./add_episode.py --gui     # the same, from a small Tk window
```

`update.py` finds the channel ID and collects candidate videos from the
channel RSS feed, the channel search for "Project Synapse", and recent uploads and
streams (through `/usr/bin/yt-dlp`; override this with `YT_DLP=...`). A video is added only if:

- its title contains "Project Synapse" (so daily Tech News Day shows are skipped)
  and doesn't say replay/encore,
- its ID isn't already listed and isn't in `ignored_ids.txt`, and
- it was published after the newest listed episode. Older unlisted videos are
  reported but not added: inserting one renumbers every later episode, which
  shouldn't happen unattended. If one is genuine, add it with `add_episode.py`.

Episodes are numbered 1..N by air date. New episodes take the next numbers
(highest + 1) in publication order; `update.py` warns if the existing list has gaps
or numbers out of date order, since highest + 1 would then be wrong. Dates are the
yt-dlp publication timestamp converted to America/Toronto, not YouTube's UTC
`upload_date`, so evening uploads keep the right day. The blurb is the YouTube description with links, sponsor
lines, chapter markers and headline lines removed, cut to about 600 characters at
a sentence boundary. Check the titles and blurbs before publishing.

`add_episode.py` refuses titles without "Project Synapse" unless you pass `--force`.
It places the episode by air date and renumbers the list, so back-filling an older
episode moves every later one up by one (it reports how many moved). `--number N`
sets the number yourself and skips renumbering.

Videos that look like episodes but aren't (cross-posts, re-uploads, specials) go in
`ignored_ids.txt` with a comment saying why.

## Weekly automatic update (systemd user timer)

`deploy/run-update.sh` runs `update.py` and the tests. If anything changed, it
commits `episodes.json` and `index.html` and, only when something new was committed, runs `git push origin HEAD`. It refuses
to run if the checked-out branch isn't `$SYNAPSE_BRANCH` (default `master`)
or if those files have uncommitted edits.

The units are provided but not enabled. To install them:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/project-synapse-update.{service,timer} ~/.config/systemd/user/
# edit the paths/branch in the .service file if the repo lives elsewhere
systemctl --user daemon-reload
systemctl --user enable --now project-synapse-update.timer
systemctl --user start project-synapse-update.service   # optional: run once now
journalctl --user -u project-synapse-update.service     # logs
```

The timer fires on Sundays at 10:00, with up to 30 minutes of random delay. If the
machine was off at that time, it runs on next boot.

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests use only the standard library and never touch the network. One test fails
if `index.html` is out of date with `episodes.json`.
