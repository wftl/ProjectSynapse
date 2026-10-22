import tempfile
import unittest
from pathlib import Path

import synapse_youtube as youtube


class TitleFilterTest(unittest.TestCase):
    def test_accepts_project_synapse_titles(self):
        for title in ("Project Synapse - AI Out of Control",
                      "Will AI Kill Capitalism? | Project Synapse",
                      "PROJECT  SYNAPSE  on Hashtag Trending"):
            self.assertTrue(youtube.is_project_synapse_title(title), title)

    def test_rejects_daily_shows_and_reruns(self):
        for title in ("Cybercriminals hack Staples to steal millions in gift cards",
                      "Gemini 3.0 Rocks. Hashtag Trending Weekend With Project Synapse (Replay)",
                      "Gemini 3.0 Rocks!: Project Synapse Holiday Encore:",
                      "Synapse project notes"):
            self.assertFalse(youtube.is_project_synapse_title(title), title)


class VideoIdTest(unittest.TestCase):
    def test_extracts_from_common_url_shapes(self):
        for url in ("https://www.youtube.com/watch?v=_yRqgQqNElI",
                    "https://www.youtube.com/watch?feature=share&v=_yRqgQqNElI&t=30",
                    "https://youtu.be/_yRqgQqNElI?si=abc",
                    "https://www.youtube.com/embed/_yRqgQqNElI",
                    "https://www.youtube.com/live/_yRqgQqNElI",
                    "  _yRqgQqNElI  "):
            self.assertEqual(youtube.extract_video_id(url), "_yRqgQqNElI", url)

    def test_rejects_urls_without_an_id(self):
        for url in ("https://www.youtube.com/@technewsday", "https://youtu.be/tooshort", ""):
            with self.assertRaises(ValueError):
                youtube.extract_video_id(url)


class TrimDescriptionTest(unittest.TestCase):
    def test_drops_headline_promo_links_and_chapters(self):
        description = (
            "Big Headline: Robots, Chips and More\n\n"
            "Join our Discord: https://discord.gg/xyz\n"
            "And checkout Marcel's video. https://www.youtube.com/watch?v=pfAh5oQDPDM\n\n"
            "This episode is brought to you by NordLayer.\n\n"
            "The hosts discuss robots in depth and why prices are falling fast. They also cover new chips "
            "for local inference and what that means for cloud vendors. NordLayer sponsors the episode.\n\n"
            "00:00 Intro\n03:12 Robots\n"
        )
        self.assertEqual(
            youtube.trim_description(description),
            "The hosts discuss robots in depth and why prices are falling fast. They also cover new chips "
            "for local inference and what that means for cloud vendors.",
        )

    def test_keeps_closing_quotes_on_sentences(self):
        self.assertEqual(youtube.trim_description("They call it “the singularity.” Then robots."),
                         "They call it “the singularity.” Then robots.")

    def test_truncates_at_sentence_boundary(self):
        description = " ".join(f"Sentence number {index} is here." for index in range(100))
        blurb = youtube.trim_description(description, max_chars=100)
        self.assertLessEqual(len(blurb), 100)
        self.assertTrue(blurb.endswith("."))

    def test_single_huge_sentence_is_cut_with_ellipsis(self):
        blurb = youtube.trim_description("word " * 300 + "end.", max_chars=50)
        self.assertLessEqual(len(blurb), 51)
        self.assertTrue(blurb.endswith("…"))

    def test_headline_only_description_falls_back_to_headline(self):
        self.assertEqual(youtube.trim_description("Just A Headline\n\nhttps://example.com"), "Just A Headline")

    def test_empty_description(self):
        self.assertEqual(youtube.trim_description(""), "")


class ShowDateTest(unittest.TestCase):
    def test_late_evening_upload_keeps_toronto_date(self):
        # 2026-08-08 03:08 UTC is 23:08 on Aug 7 in Toronto (the "August 7 2026" episode).
        self.assertEqual(youtube.show_date({"timestamp": 1786158513, "upload_date": "20260808"}), "2026-08-07")

    def test_falls_back_to_upload_date(self):
        self.assertEqual(youtube.show_date({"upload_date": "20261016"}), "2026-10-16")

    def test_missing_date_raises(self):
        with self.assertRaises(youtube.YouTubeError):
            youtube.show_date({"id": "x"})


class RssAndIgnoreListTest(unittest.TestCase):
    def test_parse_rss(self):
        feed = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry><yt:videoId>pCeBgwrXlqI</yt:videoId><title>Will AI Kill Capitalism? | Project Synapse</title></entry>
  <entry><yt:videoId>Zm2GQv8yp3s</yt:videoId><title>Special Report</title></entry>
</feed>"""
        self.assertEqual(youtube.parse_rss(feed), [
            ("pCeBgwrXlqI", "Will AI Kill Capitalism? | Project Synapse"),
            ("Zm2GQv8yp3s", "Special Report"),
        ])

    def test_ignored_ids_skip_comments_and_blanks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ignored.txt"
            path.write_text("# header\n\np2FHsWfLsl4  # note\n", encoding="utf-8")
            self.assertEqual(youtube.load_ignored_ids(path), {"p2FHsWfLsl4"})
            self.assertEqual(youtube.load_ignored_ids(Path(directory) / "absent.txt"), set())


if __name__ == "__main__":
    unittest.main()
