import tempfile
import unittest
from pathlib import Path

import synapse_youtube as youtube


class EpisodeFilterTest(unittest.TestCase):
    def test_accepts_project_synapse_titles(self):
        for title in ("Project Synapse - AI Out of Control",
                      "Will AI Kill Capitalism? | Project Synapse",
                      "PROJECT  SYNAPSE  on Hashtag Trending"):
            self.assertTrue(youtube.is_project_synapse_video(title), title)

    def test_accepts_show_named_only_in_description(self):
        self.assertTrue(youtube.is_project_synapse_video(
            "Who is Paying People to Trash AI?", "On Project Synapse for Saturday, September 12, Jim..."))
        self.assertTrue(youtube.is_project_synapse_video("When We Finally Get To Google I/O", "#projectsynapse #ainews"))

    def test_rejects_daily_shows_and_reruns(self):
        for title in ("Cybercriminals hack Staples to steal millions in gift cards",
                      "Gemini 3.0 Rocks. Hashtag Trending Weekend With Project Synapse (Replay)",
                      "Gemini 3.0 Rocks!: Project Synapse Holiday Encore:",
                      "Synapse project notes"):
            self.assertFalse(youtube.is_project_synapse_video(title), title)

    def test_rejects_rerun_flagged_in_description(self):
        self.assertFalse(youtube.is_project_synapse_video(
            "Gemini 3.0 Rocks!", "A replay of last week's Project Synapse."))

    def test_rejects_cybersecurity_today_cross_posts(self):
        self.assertFalse(youtube.is_project_synapse_video(
            "AI in Action: Project Synapse with Marcel Gagne and John Pinard. Cyber Security Today, Nov 16, 2024"))
        # Naming Cybersecurity Today in the description alone is fine (Ep 33 was shared with its listeners).
        self.assertTrue(youtube.is_project_synapse_video(
            "AI Anxiety", "A special edition of Project Synapse shared with Cybersecurity Today listeners."))


class FormatTitleTest(unittest.TestCase):
    def test_prefixes_titles_without_the_show_name(self):
        self.assertEqual(youtube.format_title("AI Backlash"), "Project Synapse: AI Backlash")

    def test_moves_a_trailing_show_name_to_the_prefix(self):
        for title, expected in (
            ("Will AI Kill Capitalism? | Project Synapse", "Will AI Kill Capitalism?"),
            ("Clawbot, Moltbot and the Overview Effect: Project Synapse", "Clawbot, Moltbot and the Overview Effect"),
            ("Running Models Locally (Project Synapse)", "Running Models Locally"),
            ("SpaceX IPO, Decentralization & Project Synapse", "SpaceX IPO, Decentralization"),
            ("Risks You Can't Ignore - Project Synapse", "Risks You Can't Ignore"),
        ):
            self.assertEqual(youtube.format_title(title), f"Project Synapse: {expected}", title)

    def test_normalizes_a_leading_show_name(self):
        for title in ("Project Synapse - AI Out of Control", "Project Synapse — AI Out of Control",
                      "project  synapse AI Out of Control", "Project Synapse: AI Out of Control"):
            self.assertEqual(youtube.format_title(title), "Project Synapse: AI Out of Control", title)

    def test_is_idempotent_and_collapses_whitespace(self):
        once = youtube.format_title("  Agents,  Robots  ")
        self.assertEqual(once, "Project Synapse: Agents, Robots")
        self.assertEqual(youtube.format_title(once), once)

    def test_bare_show_name_and_mid_title_mentions_are_left_alone(self):
        self.assertEqual(youtube.format_title("Project Synapse"), "Project Synapse")
        mid = "AI Use Cases: Hashtag Trending with Project Synapse, December 7, 2024"
        self.assertEqual(youtube.format_title(mid), mid)


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

    def test_drops_sponsor_paragraphs_and_their_ad_copy(self):
        description = (
            "Hashtag Trending would like to thank Meter for their support in bringing you this podcast. "
            "Meter delivers a complete networking stack, wired, wireless and cellular in one integrated "
            "solution that's built for performance and scale.\n\n"
            "You can find them at Meter.com/htt\n\n"
            "The panel debates AI consciousness and robots.\n\n"
            "This episode is brought to you by NordLayer.  Visit nordlayer.com/hashtagtrending and use the "
            "discount code NLSUMMER26 for a special discount on your purchase\n"
            "Hashtag Trending thanks Meter for supporting this podcast. Meter delivers a complete stack. "
            "Learn more at Meter.com/htt.\n"
            "Support us at: buymeacoffee.com/techpodcast\n"
            "Get 20% off with promo code SYNAPSE today.\n"
        )
        self.assertEqual(youtube.trim_description(description), "The panel debates AI consciousness and robots.")

    def test_sponsor_sentence_inside_prose_drops_only_that_sentence(self):
        self.assertEqual(
            youtube.trim_description("The hosts discuss chips. Special thanks to Meter for supporting the podcast. "
                                     "They also cover robots."),
            "The hosts discuss chips. They also cover robots.")

    def test_keeps_prose_that_only_resembles_sponsor_text(self):
        prose = ("State-sponsored hackers target AI labs. Should you say please and thank you to AI? "
                 "The team covers support challenges for people with disabilities.")
        self.assertEqual(youtube.trim_description(prose), prose)

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


class EpisodeFromMetadataTest(unittest.TestCase):
    def test_title_is_formatted(self):
        episode = youtube.episode_from_metadata(
            {"id": "gG1LMitW114", "title": " Agents,  Robots | Project Synapse", "upload_date": "20261002"}, 51)
        self.assertEqual(episode["title"], "Project Synapse: Agents, Robots")
        self.assertEqual(episode["blurb"], "")


class RssAndIgnoreListTest(unittest.TestCase):
    def test_parse_rss(self):
        feed = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <entry><yt:videoId>pCeBgwrXlqI</yt:videoId><title>Will AI Kill Capitalism? | Project Synapse</title>
    <media:group><media:description>On Project Synapse this week</media:description></media:group></entry>
  <entry><yt:videoId>Zm2GQv8yp3s</yt:videoId><title>Special Report</title></entry>
</feed>"""
        self.assertEqual(youtube.parse_rss(feed), [
            youtube.listing("pCeBgwrXlqI", "Will AI Kill Capitalism? | Project Synapse", "On Project Synapse this week"),
            youtube.listing("Zm2GQv8yp3s", "Special Report"),
        ])

    def test_ignored_ids_skip_comments_and_blanks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ignored.txt"
            path.write_text("# header\n\np2FHsWfLsl4  # note\n", encoding="utf-8")
            self.assertEqual(youtube.load_ignored_ids(path), {"p2FHsWfLsl4"})
            self.assertEqual(youtube.load_ignored_ids(Path(directory) / "absent.txt"), set())


if __name__ == "__main__":
    unittest.main()
