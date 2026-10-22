import unittest
from unittest import mock

import add_episode
import update

EXISTING = [
    {"number": 43, "title": "Ep 43", "date": "2026-07-10", "youtube_id": "bOZE0vtb0bs", "blurb": "x"},
    {"number": 42, "title": "Ep 42", "date": "2026-06-19", "youtube_id": "JyDQ3ZZmcYo", "blurb": "x"},
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
                         [(44, "newBBBBBBBB", "2026-07-24"), (45, "newerAAAAAA", "2026-10-16")])
        self.assertNotIn("dailyFFFFFF", fetched)
        self.assertNotIn("ignoredEEEE", fetched)
        self.assertNotIn("bOZE0vtb0bs", fetched)

    def test_nothing_new(self):
        self.assertEqual(update.select_new_episodes({}, EXISTING, set(), None, print), [])


class AddEpisodeTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch("build.load_episodes", return_value=list(EXISTING)),
            mock.patch("build.save_episodes"),
            mock.patch("build.build", return_value=3),
        ]
        self.load, self.save, self.rebuild = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def fetch(self, video_id):
        return VIDEOS[video_id]

    def test_appends_with_next_number_and_rebuilds(self):
        episode = add_episode.add_episode("https://youtu.be/newerAAAAAA", fetch_video=self.fetch)
        self.assertEqual(episode["number"], 44)
        self.assertEqual(self.save.call_args.args[0][-1], episode)
        self.rebuild.assert_called_once()

    def test_rejects_already_listed(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("https://www.youtube.com/watch?v=bOZE0vtb0bs", fetch_video=self.fetch)
        self.save.assert_not_called()

    def test_rejects_non_synapse_title_unless_forced(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("renamedDDDD", fetch_video=self.fetch)
        episode = add_episode.add_episode("renamedDDDD", force=True, fetch_video=self.fetch)
        self.assertEqual(episode["title"], "Daily news")

    def test_rejects_taken_number(self):
        with self.assertRaises(add_episode.AddEpisodeError):
            add_episode.add_episode("newerAAAAAA", number=42, fetch_video=self.fetch)


if __name__ == "__main__":
    unittest.main()
