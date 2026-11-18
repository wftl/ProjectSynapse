import re
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import build
import feed
from test_build import CARD_TEMPLATE, PAGE_TEMPLATE, make_episode

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"


def parse_channel(episodes):
    return ElementTree.fromstring(feed.render_feed(episodes)).find("channel")


class CommittedFeedTest(unittest.TestCase):
    def test_feed_xml_is_up_to_date_with_episodes_json(self):
        rendered = feed.render_feed(build.load_episodes())
        self.assertEqual(rendered, build.FEED_PATH.read_text(encoding="utf-8"),
                         "feed.xml is stale: run ./build.py")

    def test_committed_feed_parses_and_lists_every_episode(self):
        root = ElementTree.parse(build.FEED_PATH).getroot()
        self.assertEqual(len(root.findall("channel/item")), len(build.load_episodes()))


class ChannelTest(unittest.TestCase):
    def test_channel_metadata(self):
        channel = parse_channel([make_episode(1)])
        self.assertEqual(channel.findtext("title"), "Project Synapse")
        self.assertEqual(channel.findtext("link"), "https://projectsynapse.ca/")
        self.assertEqual(channel.findtext("language"), "en")
        self.assertTrue(channel.findtext("description"))
        self_link = channel.find(f"{ATOM}link")
        self.assertEqual(self_link.attrib, {
            "href": "https://projectsynapse.ca/feed.xml",
            "rel": "self",
            "type": "application/rss+xml",
        })

    def test_last_build_date_is_newest_episode_date_not_now(self):
        # Highest-numbered episode isn't the newest date here, to prove max() over dates.
        episodes = [make_episode(1, date="2026-11-14"), make_episode(2, date="2026-03-01")]
        self.assertEqual(parse_channel(episodes).findtext("lastBuildDate"),
                         "Sat, 14 Nov 2026 12:00:00 +0000")

    def test_output_is_deterministic(self):
        episodes = [make_episode(1), make_episode(2)]
        self.assertEqual(feed.render_feed(episodes), feed.render_feed(list(reversed(episodes))))


class ItemTest(unittest.TestCase):
    def test_items_newest_first(self):
        episodes = [make_episode(2), make_episode(10), make_episode(3)]
        titles = [item.findtext("title") for item in parse_channel(episodes).findall("item")]
        self.assertEqual(titles, ["Episode title 10", "Episode title 3", "Episode title 2"])

    def test_item_fields(self):
        episode = make_episode(1, youtube_id="dQw4w9WgXcQ", date="2026-03-01", blurb="Short.")
        item = parse_channel([episode]).find("item")
        self.assertEqual(item.findtext("link"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        guid = item.find("guid")
        self.assertEqual(guid.text, "yt:video:dQw4w9WgXcQ")
        self.assertEqual(guid.get("isPermaLink"), "false")
        self.assertEqual(item.findtext("pubDate"), "Sun, 01 Mar 2026 12:00:00 +0000")
        self.assertEqual(item.findtext("description"), "Short.")
        thumbnail = item.find(f"{MEDIA}thumbnail")
        self.assertEqual(thumbnail.get("url"), "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

    def test_markup_in_title_and_blurb_is_escaped_and_round_trips(self):
        title = 'AI & <Robots> "quoted" ]]>'
        blurb = "Say <b>hi</b> & <script>alert(1)</script>"
        text = feed.render_feed([make_episode(1, title=title, blurb=blurb)])
        self.assertNotIn("<script>", text)
        self.assertNotIn("<Robots>", text)
        item = ElementTree.fromstring(text).find("channel/item")
        self.assertEqual(item.findtext("title"), title)
        self.assertEqual(item.findtext("description"), blurb)

    def test_unicode_is_kept_and_xml_forbidden_characters_are_dropped(self):
        text = feed.render_feed([make_episode(1, title="Gagné — “AI”", blurb="bad\x0bchar\x00s")])
        item = ElementTree.fromstring(text.encode("utf-8")).find("channel/item")
        self.assertEqual(item.findtext("title"), "Gagné — “AI”")
        self.assertEqual(item.findtext("description"), "badchars")

    def test_pub_date_uses_english_names_with_two_digit_day(self):
        self.assertEqual(feed.rfc822_date("2026-12-05"), "Sat, 05 Dec 2026 12:00:00 +0000")


class BuildWritesFeedTest(unittest.TestCase):
    def test_build_writes_page_and_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            build.save_episodes([make_episode(1), make_episode(2)], directory / "episodes.json")
            count = build.build(directory / "episodes.json", directory / "index.html", directory / "feed.xml")
            self.assertEqual(count, 2)
            root = ElementTree.parse(directory / "feed.xml").getroot()
            self.assertEqual(len(root.findall("channel/item")), 2)
            first = (directory / "feed.xml").read_bytes()
            build.build(directory / "episodes.json", directory / "index.html", directory / "feed.xml")
            self.assertEqual((directory / "feed.xml").read_bytes(), first)


class PageLinksFeedTest(unittest.TestCase):
    def test_page_head_advertises_feed(self):
        page = build.render_page([make_episode(1)], PAGE_TEMPLATE, CARD_TEMPLATE)
        head = page[:page.index("</head>")]
        link = re.search(r'<link rel="alternate" type="application/rss\+xml"[^>]*>', head).group(0)
        self.assertIn('href="https://projectsynapse.ca/feed.xml"', link)
        self.assertIn("title=", link)

    def test_footer_has_visible_rss_link_next_to_discord(self):
        page = build.render_page([make_episode(1)], PAGE_TEMPLATE, CARD_TEMPLATE)
        footer_line = re.search(r'<p class="footer-discord">.*?</p>', page, re.DOTALL).group(0)
        self.assertRegex(footer_line, r'<a class="rss-link" href="https://projectsynapse\.ca/feed\.xml"')
        self.assertIn("Subscribe via RSS</a>", footer_line)


class DeployScriptTest(unittest.TestCase):
    def test_weekly_job_commits_feed_and_stages_before_diffing(self):
        script = (build.ROOT / "deploy" / "run-update.sh").read_text(encoding="utf-8")
        self.assertIn("data_files=(episodes.json index.html feed.xml podcast_episodes.json podcast.xml)", script)
        # Staging must precede the "anything changed?" check, or a not-yet-tracked
        # feed.xml is invisible to git diff and rejected by git commit.
        self.assertLess(script.index('git add -- "${data_files[@]}"'),
                        script.index('git diff --cached --quiet HEAD'))


if __name__ == "__main__":
    unittest.main()
