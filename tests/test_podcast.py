import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest.mock import patch

import build
import podcast

FIXTURE = (Path(__file__).parent / "fixtures" / "podcast.xml").read_bytes()
OLDER_GUID = "https://hashtagtrending.libsyn.com/older"
ATOM = "{http://www.w3.org/2005/Atom}"


class ParseTest(unittest.TestCase):
    def test_filters_titles_case_insensitively_not_descriptions(self):
        self.assertEqual(set(podcast.parse_episodes(FIXTURE)), {"synapse-new", OLDER_GUID})

    def test_preserves_all_source_values(self):
        source = ElementTree.fromstring(FIXTURE).find("channel/item")
        episode = podcast.parse_episodes(FIXTURE)["synapse-new"]
        for field in podcast.TEXT_FIELDS:
            self.assertEqual(episode[field], source.findtext(field))
        self.assertEqual(episode["guid_attributes"], source.find("guid").attrib)
        self.assertEqual(episode["enclosure"], source.find("enclosure").attrib)
        self.assertEqual(episode["duration"], source.findtext(f"{podcast.ITUNES}duration"))

    def test_missing_guid_enclosure_or_duration_fails(self):
        for tag in ("guid", "enclosure", f"{podcast.ITUNES}duration"):
            with self.subTest(tag=tag):
                root = ElementTree.fromstring(FIXTURE)
                item = root.find("channel/item")
                item.remove(item.find(tag))
                with self.assertRaises(ValueError):
                    podcast.parse_episodes(ElementTree.tostring(root))

    def test_rejects_invalid_dates_and_enclosure_metadata(self):
        for tag, attribute, value in (
            ("pubDate", None, "not a date"),
            ("pubDate", None, "Sat, 14 Nov 2026 05:30:00"),
            ("enclosure", "length", "0"),
            ("enclosure", "length", "unknown"),
            ("enclosure", "type", "text/html"),
        ):
            with self.subTest(tag=tag, attribute=attribute, value=value):
                root = ElementTree.fromstring(FIXTURE)
                element = root.find(f"channel/item/{tag}")
                if attribute:
                    element.set(attribute, value)
                else:
                    element.text = value
                with self.assertRaises(ValueError):
                    podcast.parse_episodes(ElementTree.tostring(root))

    def test_non_rss_response_is_rejected(self):
        with self.assertRaises(ValueError):
            podcast.parse_episodes(b"<html />")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.episodes = podcast.parse_episodes(FIXTURE)

    def test_required_channel_tags_and_namespaces(self):
        rendered = podcast.render_feed(self.episodes)
        root = ElementTree.fromstring(rendered)
        self.assertEqual(root.attrib, {"version": "2.0"})
        self.assertIn(f'xmlns:podcast="{podcast.PODCAST_NAMESPACE}"', rendered)
        channel = root.find("channel")
        for tag, value in {
            "title": "Project Synapse", "link": podcast.SITE_URL,
            "description": podcast.CHANNEL_DESCRIPTION, "language": "en-ca",
            f"{podcast.ITUNES}author": "Jim Love, Marcel Gagné, John Pinard",
            f"{podcast.ITUNES}explicit": "false", f"{podcast.ITUNES}type": "episodic",
        }.items():
            self.assertEqual(channel.findtext(tag), value)
        self.assertEqual(channel.find(f"{podcast.ITUNES}category").get("text"), "Technology")
        self.assertEqual(channel.find(f"{podcast.ITUNES}image").get("href"), podcast.COVER_ART_URL)
        owner = channel.find(f"{podcast.ITUNES}owner")
        self.assertEqual(owner.findtext(f"{podcast.ITUNES}name"), podcast.OWNER_NAME)
        self.assertIsNone(owner.find(f"{podcast.ITUNES}email"))
        self.assertEqual(channel.find(f"{ATOM}link").attrib, {
            "rel": "self", "href": podcast.FEED_URL, "type": "application/rss+xml",
        })

    def test_owner_email_only_emitted_when_configured(self):
        with patch.object(podcast, "OWNER_EMAIL", "owner@example.test"):
            channel = ElementTree.fromstring(podcast.render_feed({})).find("channel")
        self.assertEqual(channel.findtext(f"{podcast.ITUNES}owner/{podcast.ITUNES}email"),
                         "owner@example.test")

    def test_items_round_trip_original_values_and_have_audio(self):
        root = ElementTree.fromstring(podcast.render_feed(self.episodes))
        items = root.findall("channel/item")
        self.assertEqual([item.findtext("guid") for item in items], ["synapse-new", OLDER_GUID])
        for item in items:
            episode = self.episodes[item.findtext("guid")]
            for field in podcast.TEXT_FIELDS:
                self.assertEqual(item.findtext(field), episode[field])
            self.assertEqual(item.find("guid").attrib, episode["guid_attributes"])
            self.assertEqual(item.find("enclosure").attrib, episode["enclosure"])
            self.assertEqual(item.findtext(f"{podcast.ITUNES}duration"), episode["duration"])
            self.assertEqual(item.findtext(f"{podcast.ITUNES}episodeType"), "full")

    def test_missing_source_is_permalink_attribute_stays_absent(self):
        self.episodes["synapse-new"]["guid_attributes"] = {}
        item = ElementTree.fromstring(podcast.render_feed(self.episodes)).find("channel/item")
        self.assertEqual(item.find("guid").attrib, {})

    def test_deterministic_even_for_equal_dates_and_reversed_input(self):
        self.episodes[OLDER_GUID]["pubDate"] = self.episodes["synapse-new"]["pubDate"]
        reversed_episodes = dict(reversed(list(self.episodes.items())))
        self.assertEqual(podcast.render_feed(self.episodes), podcast.render_feed(reversed_episodes))

    def test_sort_uses_instants_not_date_strings(self):
        self.episodes[OLDER_GUID]["pubDate"] = "Sat, 14 Nov 2026 02:00:00 -0500"
        root = ElementTree.fromstring(podcast.render_feed(self.episodes))
        self.assertEqual(root.findtext("channel/item/guid"), OLDER_GUID)

    def test_empty_archive_renders_valid_xml(self):
        self.assertEqual(ElementTree.fromstring(podcast.render_feed({})).findall("channel/item"), [])


class RefreshTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_path = Path(directory.name) / "podcast_episodes.json"
        self.feed_path = Path(directory.name) / "podcast.xml"

    def refresh_with(self, xml):
        with patch.object(podcast, "fetch_feed", return_value=xml):
            return podcast.refresh(self.data_path, self.feed_path)

    def test_accumulates_updates_by_guid_and_never_deletes(self):
        self.assertEqual(self.refresh_with(FIXTURE), (2, 2))
        root = ElementTree.fromstring(FIXTURE)
        channel = root.find("channel")
        for item in list(channel.findall("item"))[1:]:
            channel.remove(item)
        channel.find("item/title").text = "Project Synapse: Updated source title"
        self.assertEqual(self.refresh_with(ElementTree.tostring(root)), (2, 0))
        stored = podcast.load_episodes(self.data_path)
        self.assertIn(OLDER_GUID, stored)
        self.assertEqual(stored["synapse-new"]["title"], "Project Synapse: Updated source title")
        self.assertEqual(self.refresh_with(b"<rss><channel /></rss>"), (2, 0))

    def test_unchanged_refresh_is_byte_identical(self):
        self.refresh_with(FIXTURE)
        original = (self.data_path.read_bytes(), self.feed_path.read_bytes())
        self.refresh_with(FIXTURE)
        self.assertEqual(original, (self.data_path.read_bytes(), self.feed_path.read_bytes()))

    def test_new_guid_accumulates_after_old_items_scroll_off(self):
        self.refresh_with(FIXTURE)
        root = ElementTree.fromstring(FIXTURE)
        channel = root.find("channel")
        for item in list(channel.findall("item"))[1:]:
            channel.remove(item)
        channel.find("item/guid").text = "next-week"
        self.assertEqual(self.refresh_with(ElementTree.tostring(root)), (3, 1))
        self.assertEqual(set(podcast.load_episodes(self.data_path)),
                         {"synapse-new", OLDER_GUID, "next-week"})

    def test_fetch_or_parse_failure_leaves_both_files_untouched(self):
        self.refresh_with(FIXTURE)
        original = (self.data_path.read_bytes(), self.feed_path.read_bytes())
        for failure in (urllib.error.URLError("offline"), TimeoutError("timeout")):
            with self.subTest(failure=failure), patch.object(podcast, "fetch_feed", side_effect=failure):
                with self.assertRaises(OSError):
                    podcast.refresh(self.data_path, self.feed_path)
            self.assertEqual(original, (self.data_path.read_bytes(), self.feed_path.read_bytes()))
        with self.assertRaises(ElementTree.ParseError):
            self.refresh_with(b"invalid XML")
        self.assertEqual(original, (self.data_path.read_bytes(), self.feed_path.read_bytes()))

    def test_backfill_uses_archive_then_standard_feed_and_preserves_current_values(self):
        archive = ElementTree.fromstring(FIXTURE)
        archive.find("channel/item/title").text = "Project Synapse: Archive version"
        with patch.object(podcast, "fetch_feed", side_effect=[ElementTree.tostring(archive), FIXTURE]) as fetch:
            self.assertEqual(podcast.refresh(self.data_path, self.feed_path, backfill=True), (2, 2))
        self.assertEqual(fetch.call_args_list, [unittest.mock.call(podcast.BACKFILL_URL),
                                               unittest.mock.call(podcast.SOURCE_URL)])
        self.assertEqual(podcast.load_episodes(self.data_path)["synapse-new"]["title"],
                         podcast.parse_episodes(FIXTURE)["synapse-new"]["title"])

    def test_backfill_failure_before_standard_fetch_does_not_write(self):
        with patch.object(podcast, "fetch_feed", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(OSError):
                podcast.refresh(self.data_path, self.feed_path, backfill=True)
        self.assertFalse(self.data_path.exists())
        self.assertFalse(self.feed_path.exists())

    def test_failure_after_archive_fetch_does_not_change_existing_files(self):
        self.refresh_with(FIXTURE)
        original = (self.data_path.read_bytes(), self.feed_path.read_bytes())
        with patch.object(podcast, "fetch_feed", side_effect=[FIXTURE, TimeoutError("timeout")]):
            with self.assertRaises(OSError):
                podcast.refresh(self.data_path, self.feed_path, backfill=True)
        self.assertEqual(original, (self.data_path.read_bytes(), self.feed_path.read_bytes()))

    def test_backfill_at_limit_requires_investigation_before_writing(self):
        with patch.object(podcast, "BACKFILL_LIMIT", 3), patch.object(podcast, "fetch_feed", return_value=FIXTURE):
            with self.assertRaisesRegex(ValueError, "item limit"):
                podcast.refresh(self.data_path, self.feed_path, backfill=True)
        self.assertFalse(self.data_path.exists())

    def test_invalid_store_is_not_overwritten(self):
        episodes = podcast.parse_episodes(FIXTURE)
        episodes["wrong-key"] = episodes.pop("synapse-new")
        original = json.dumps(episodes)
        self.data_path.write_text(original, encoding="utf-8")
        with self.assertRaises(ValueError):
            self.refresh_with(FIXTURE)
        self.assertEqual(self.data_path.read_text(encoding="utf-8"), original)


class IntegrationTest(unittest.TestCase):
    def test_committed_feed_matches_store_and_contains_only_synapse_audio(self):
        episodes = podcast.load_episodes()
        rendered = podcast.render_feed(episodes)
        self.assertEqual(podcast.OUTPUT_PATH.read_text(encoding="utf-8"), rendered)
        items = ElementTree.fromstring(rendered).findall("channel/item")
        self.assertTrue(items)
        self.assertEqual(len(items), len(episodes))
        for item in items:
            self.assertIn("project synapse", item.findtext("title").casefold())
            self.assertIsNotNone(item.find("enclosure"))

    def test_page_head_advertises_audio_feed(self):
        head = build.PAGE_TEMPLATE_PATH.read_text(encoding="utf-8").split("</head>")[0]
        self.assertIn('<link rel="alternate" type="application/rss+xml" '
                      'title="Project Synapse podcast (audio)" '
                      'href="https://projectsynapse.ca/podcast.xml" />', head)

    def test_weekly_update_continues_after_podcast_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            deploy = directory / "deploy"
            deploy.mkdir()
            script = deploy / "run-update.sh"
            script.write_bytes((build.ROOT / "deploy" / "run-update.sh").read_bytes())
            git = directory / "git"
            git.write_text('#!/bin/sh\nif [ "$1" = symbolic-ref ]; then echo master; fi\nexit 0\n')
            python = directory / "python3"
            python.write_text('#!/bin/sh\necho "python: $*"\nif [ "$1" = podcast.py ]; then exit 1; fi\n')
            git.chmod(0o700)
            python.chmod(0o700)
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                    env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                                         "SYNAPSE_BRANCH": "master"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("python: update.py", result.stdout)
        self.assertIn("python: -m unittest discover -s tests -q", result.stdout)
        self.assertIn("continuing with the existing podcast files", result.stderr)


if __name__ == "__main__":
    unittest.main()
