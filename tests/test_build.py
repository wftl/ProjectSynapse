import json
import tempfile
import unittest
from pathlib import Path

import build


def make_episode(number, **overrides):
    episode = {
        "number": number,
        "title": f"Episode title {number}",
        "date": "2026-01-0" + str(number % 9 + 1),
        "youtube_id": f"abcdefghi{number:02d}",
        "blurb": "A blurb long enough to need the Read more button. " * 5,
    }
    episode.update(overrides)
    return episode


CARD_TEMPLATE = build.CARD_TEMPLATE_PATH.read_text(encoding="utf-8")
PAGE_TEMPLATE = build.PAGE_TEMPLATE_PATH.read_text(encoding="utf-8")


class CommittedPageTest(unittest.TestCase):
    def test_index_html_is_up_to_date_with_episodes_json(self):
        rendered = build.render_page(build.load_episodes(), PAGE_TEMPLATE, CARD_TEMPLATE)
        self.assertEqual(rendered, build.OUTPUT_PATH.read_text(encoding="utf-8"),
                         "index.html is stale: run ./build.py")


class RenderTest(unittest.TestCase):
    def test_display_date_has_no_leading_zero(self):
        self.assertEqual(build.format_display_date("2026-03-01"), "March 1, 2026")

    def test_title_and_blurb_are_html_escaped(self):
        card = build.render_card(make_episode(1, title="AI & <Robots>", blurb='Say "hi" & <b>'), CARD_TEMPLATE)
        self.assertIn("AI &amp; &lt;Robots&gt;", card)
        self.assertIn('Say "hi" &amp; &lt;b&gt;', card)

    def test_placeholders_inside_data_are_not_expanded(self):
        card = build.render_card(make_episode(7, title="{{NUMBER}} {{BLURB}}"), CARD_TEMPLATE)
        self.assertIn('<div class="card-title">{{NUMBER}} {{BLURB}}</div>', card)

    def test_short_blurb_has_no_toggle_button(self):
        self.assertNotIn("toggle-btn", build.render_card(make_episode(1, blurb="Short."), CARD_TEMPLATE))
        self.assertIn("toggle-btn", build.render_card(make_episode(1), CARD_TEMPLATE))

    def test_page_orders_by_number_descending_and_counts(self):
        episodes = [make_episode(2, date="2025-05-01"), make_episode(10, date="2026-05-01"), make_episode(3)]
        page = build.render_page(episodes, PAGE_TEMPLATE, CARD_TEMPLATE)
        positions = [page.index(f"<!-- EP {n} -->") for n in (10, 3, 2)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('<div class="stat-number">3</div>', page)
        self.assertIn('<div class="stat-number">2025–2026</div>', page)

    def test_single_year_range(self):
        self.assertEqual(build.year_range([make_episode(1, date="2026-02-02")]), "2026")

    def test_unknown_placeholder_fails_loudly(self):
        with self.assertRaises(KeyError):
            build.fill_template("{{MISSING}}", {})


class ValidationTest(unittest.TestCase):
    def assert_invalid(self, episodes):
        with self.assertRaises((build.EpisodeDataError, ValueError)):
            build.validate_episodes(episodes)

    def test_rejects_malformed_youtube_id(self):
        self.assert_invalid([make_episode(1, youtube_id='bad"><script>')])

    def test_rejects_duplicate_number_and_id(self):
        self.assert_invalid([make_episode(1), make_episode(1, youtube_id="zzzzzzzzzzz")])
        self.assert_invalid([make_episode(1), make_episode(2, youtube_id=make_episode(1)["youtube_id"])])

    def test_rejects_bad_date_and_missing_field(self):
        self.assert_invalid([make_episode(1, date="July 4, 2026")])
        episode = make_episode(1)
        del episode["blurb"]
        self.assert_invalid([episode])


class NumberingTest(unittest.TestCase):
    def test_renumber_orders_by_date_closes_gaps_and_reports_moves(self):
        episodes = [
            make_episode(7, date="2026-03-01"),
            make_episode(2, date="2026-01-01"),
            make_episode(9, date="2026-02-01"),
        ]
        changes = build.renumber_chronologically(episodes)
        self.assertEqual(sorted((episode["date"], episode["number"]) for episode in episodes),
                         [("2026-01-01", 1), ("2026-02-01", 2), ("2026-03-01", 3)])
        self.assertEqual(changes, {
            make_episode(2)["youtube_id"]: (2, 1),
            make_episode(9)["youtube_id"]: (9, 2),
            make_episode(7)["youtube_id"]: (7, 3),
        })

    def test_renumber_keeps_existing_order_for_same_day_and_reports_nothing_when_correct(self):
        episodes = [make_episode(1, date="2026-01-01"), make_episode(2, date="2026-01-01")]
        self.assertEqual(build.renumber_chronologically(episodes), {})
        self.assertEqual([episode["number"] for episode in episodes], [1, 2])

    def test_numbering_problems(self):
        good = [make_episode(1, date="2026-01-01"), make_episode(2, date="2026-01-08")]
        self.assertEqual(build.numbering_problems(good), [])
        gap = [make_episode(1, date="2026-01-01"), make_episode(3, date="2026-01-08")]
        self.assertEqual(build.numbering_problems(gap), ["episode numbers skip from 1 to 3"])
        backwards = [make_episode(1, date="2026-01-08"), make_episode(2, date="2026-01-01")]
        self.assertEqual(build.numbering_problems(backwards),
                         ["Ep 1 (2026-01-08) is dated after Ep 2 (2026-01-01)"])


class PersistenceTest(unittest.TestCase):
    def test_save_sorts_descending_and_round_trips_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.json"
            build.save_episodes([make_episode(1, title="Gagné — “AI”"), make_episode(5)], path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([episode["number"] for episode in saved], [5, 1])
            self.assertIn("Gagné — “AI”", path.read_text(encoding="utf-8"))
            self.assertEqual(build.load_episodes(path), saved)


if __name__ == "__main__":
    unittest.main()
