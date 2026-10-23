import copy
import unittest
from unittest import mock

import add_episode
import update

EXISTING = [
    {"number": 2, "title": "Ep 2", "date": "2026-07-10", "youtube_id": "bOZE0vtb0bs", "blurb": "x"},
    {"number": 1, "title": "Ep 1", "date": "2026-06-19", "youtube_id": "JyDQ3ZZmcYo", "blurb": "x"},
]


def metadata(video_id, title, timestamp):
    return {"id": video_id, "title": title, "timestamp": timestamp, "description": "A summary."}


VIDEOS = {
    "newerAAAAAA": metadata("newerAAAAAA", "Project Synapse: Later", 1792180703),     # 2026-10-16
    "newBBBBBBBB": metadata("newBBBBBBBB", "Robots | Project Synapse", 1784933664),   # 2026-07-24
    "olderCCCCCC": metadata("olderCCCCCC", "Project Synapse July 4", 1783180800),     # 2026-07-04
    "renamedDDDD": metadata("renamedDDDD", "Daily news", 1790000000),
    "ignoredEEEE": metadata("ignoredEEEE", "Project Synapse special", 1790000000),
}


class SelectNewEpisodesTest(unittest.TestCase):
    def test_adds_only_newer_project_synapse_videos_in_date_order(self):
        candidates = {
            "newerAAAAAA": "Project Synapse: Later",
            "bOZE0vtb0bs": "Project Synapse already listed",
            "newBBBBBBBB": "Robots | Project Synapse",
            "olderCCCCCC": "Project Synapse July 4",
            "renamedDDDD": "Project Synapse (flat title differs)",
            "ignoredEEEE": "Project Synapse special",
            "dailyFFFFFF": "Tech News Day: chips",
        }
        fetched = []

        def fake_fetch(video_id):
            fetched.append(video_id)
            return VIDEOS[video_id]

        new = update.select_new_episodes(candidates, EXISTING, {"ignoredEEEE"}, fake_fetch, lambda message: None)
        self.assertEqual([(e["number"], e["youtube_id"], e["date"]) for e in new],
                         [(3, "newBBBBBBBB", "2026-07-24"), (4, "newerAAAAAA", "2026-10-16")])
        self.assertNotIn("dailyFFFFFF", fetched)
        self.assertNotIn("ignoredEEEE", fetched)
        self.assertNotIn("bOZE0vtb0bs", fetched)

    def test_nothing_new(self):
        self.assertEqual(update.select_new_episodes({}, EXISTING, set(), None, print), [])

    def test_reports_older_videos_without_adding_them(self):
        messages = []
        new = update.select_new_episodes({"olderCCCCCC": "Project Synapse July 4"}, EXISTING, set(),
                                         VIDEOS.get, messages.append)
        self.assertEqual(new, [])
        self.assertTrue(any("olderCCCCCC" in message and "add_episode.py" in message for message in messages))

    def test_warns_when_existing_numbering_is_not_chronological(self):
        out_of_order = [dict(EXISTING[0], number=1), dict(EXISTING[1], number=2)]
        gappy = [dict(EXISTING[0], number=5), dict(EXISTING[1], number=1)]
        for episodes, expected in ((EXISTING, None), (gappy, "skip from 1 to 5"), (out_of_order, "dated after")):
            messages = []
            update.select_new_episodes({}, episodes, set(), None, messages.append)
            warnings = [message for message in messages if message.startswith("warning:")]
            if expected:
                self.assertTrue(any(expected in warning for warning in warnings), warnings)
            else:
                self.assertEqual(warnings, [])


class AddEpisodeTest(unittest.TestCase):
    def setUp(self):
        patches = [
            # Deep copy: add_episode renumbers the loaded dicts in place.
            mock.patch("build.load_episodes", return_value=copy.deepcopy(EXISTING)),
            mock.patch("build.save_episodes"),
            mock.patch("build.build", return_value=3),
        ]
        self.load, self.save, self.rebuild = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def fetch(self, video_id):
        return VIDEOS[video_id]

    def saved(self):
        return {episode["youtube_id"]: episode["number"] for episode in self.save.call_args.args[0]}

    def test_newest_episode_gets_next_number_and_rebuilds(self):
        episode, renumbered = add_episode.add_episode("https://youtu.be/newerAAAAAA", fetch_video=self.fetch)
        self.assertEqual(episode["number"], 3)
        self.assertEqual(renumbered, {})
        self.assertEqual(self.saved(), {"JyDQ3ZZmcYo": 1, "bOZE0vtb0bs": 2, "newerAAAAAA": 3})
        self.rebuild.assert_called_once()

    def test_older_episode_is_inserted_by_date_and_later_ones_renumbered(self):
        episode, renumbered = add_episode.add_episode("olderCCCCCC", fetch_video=self.fetch)
        self.assertEqual((episode["number"], episode["date"]), (2, "2026-07-04"))
        self.assertEqual(renumbered, {"bOZE0vtb0bs": (2, 3)})
        self.assertEqual(self.saved(), {"JyDQ3ZZmcYo": 1, "olderCCCCCC": 2, "bOZE0vtb0bs": 3})
        self.assertIn("renumbered 1 other episodes", add_episode.describe(episode, renumbered))

    def test_explicit_number_is_used_without_renumbering(self):
        episode, renumbered = add_episode.add_episode("olderCCCCCC", number=99, fetch_video=self.fetch)
        self.assertEqual((episode["number"], renumbered), (99, {}))
        self.assertEqual(self.saved()["bOZE0vtb0bs"], 2)

    def test_rejects_already_listed(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("https://www.youtube.com/watch?v=bOZE0vtb0bs", fetch_video=self.fetch)
        self.save.assert_not_called()

    def test_rejects_non_synapse_title_unless_forced(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("renamedDDDD", fetch_video=self.fetch)
        episode, _ = add_episode.add_episode("renamedDDDD", force=True, fetch_video=self.fetch)
        self.assertEqual(episode["title"], "Daily news")

    def test_rejects_taken_number(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("newerAAAAAA", number=2, fetch_video=self.fetch)


if __name__ == "__main__":
    unittest.main()
