"""What a player hears: the commentator's lines in the Watch payload, driven through the observer."""
import json
import os
import unittest
from unittest import mock

from app import commentator
from tests.kit import Table

POT_5 = dict(shooting="Ada", potted=[["5", "solid", "top-right", "Ada"]], summary="Ada pots the 5")


class Lines(unittest.TestCase):
    def setUp(self):
        self.table = Table(["Ada", "Sam"])

    def tearDown(self):
        self.table.close()

    def last(self):
        return self.table.said()[-1]

    def test_a_new_game_announces_who_breaks(self):
        self.assertEqual(self.table.said(), [("New game. Ada to break against Sam.", "normal")])

    def test_the_live_camera_says_nothing_before_a_game_starts(self):
        from app.commentator import Commentator
        from app.observer import Observer
        from tests.kit import Camera
        observer = Observer("idle", Camera(), lambda: None, active=False, commentator=Commentator())
        try:
            self.assertEqual(observer.summary()["lines"], [])
        finally:
            observer.stop()

    def test_a_pot_names_ball_pocket_and_player_once(self):
        self.table.look(**POT_5)
        self.assertEqual(self.last(), ("Ada pots the 5 in the top right.", "normal"))
        before = len(self.table.lines())
        self.table.look(**POT_5)  # the overlap photo shows the same pot again
        self.assertEqual(len(self.table.lines()), before)

    def test_the_eight_is_called_the_eight(self):
        self.table.look(shooting="Ada", potted=[["8", "eight", "side", "Ada"]])
        self.assertEqual(self.last()[0], "Ada pots the eight in the side.")

    def test_a_scratch_is_critical(self):
        self.table.look(shooting="Ada", potted=[["cue", "cue", "corner", "Ada"]])
        self.assertEqual(self.last(), ("Scratch by Ada.", "critical"))

    def test_a_foul_says_why_and_is_critical(self):
        self.table.look(shooting="Sam", foul="Ada hit no rail")
        text, priority = self.last()
        self.assertIn("Foul. Ada hit no rail.", text)
        self.assertEqual(priority, "critical")

    def test_groups_taken(self):
        self.table.look(**POT_5, groups={"Ada": "solids"})
        self.assertEqual(self.last()[0], "Ada pots the 5 in the top right. Ada takes solids. Sam has stripes.")
        before = len(self.table.lines())
        self.table.look(shooting="Ada", groups={"Ada": "solids"})  # already known: not said again
        self.assertEqual(len(self.table.lines()), before)

    def test_a_turn_change(self):
        self.table.look(shooting="Sam", summary="Ada misses")
        self.assertEqual(self.last(), ("Sam to shoot.", "normal"))

    def test_no_turn_line_when_the_same_player_stays_at_the_table(self):
        self.table.look(shooting="Ada", summary="Ada lines up")
        self.assertEqual(len(self.table.lines()), 1)  # only the break line

    def test_a_correction_is_critical(self):
        self.table.look(**POT_5)
        self.table.look(shooting="Ada", back=["5"])
        self.assertEqual(self.last(), ("Correction. The 5 is still on the table, not potted.", "critical"))

    def test_the_winner_is_announced_once_two_looks_agree(self):
        self.table.look(shooting="Ada", potted=[["8", "eight", "corner", "Ada"]], winner="Ada")
        self.assertNotIn("wins", self.last()[0])
        self.table.look(shooting="Ada", winner="Ada")
        self.assertEqual(self.last(), ("Game over. Ada wins.", "critical"))
        self.assertEqual(self.table.observer.summary(None)["lines"][-1]["text"], "Game over. Ada wins.")

    def test_lines_carry_id_priority_and_game(self):
        self.table.look(**POT_5)
        a, b = self.table.lines()
        self.assertLess(a["id"], b["id"])
        self.assertEqual(a["game"], self.table.observer.game_id)

    def test_a_new_game_starts_clean_and_keeps_counting_ids(self):
        self.table.look(**POT_5)
        last_id = self.table.lines()[-1]["id"]
        self.table.observer.new_game(["Sam", "Ada"])
        self.assertEqual(self.table.texts(), ["New game. Sam to break against Ada."])
        self.assertGreater(self.table.lines()[0]["id"], last_id)

    def test_the_watch_payload_keeps_its_fields_and_the_latest_20_lines(self):
        for i in range(12):
            self.table.look(shooting="Sam" if i % 2 == 0 else "Ada")
        watch = self.table.observer.summary()
        self.assertEqual(set(watch), {"active", "match", "winner", "players", "events", "lines"})
        self.assertEqual(len(watch["lines"]), 13)
        for i in range(10):
            self.table.look(shooting="Sam" if i % 2 == 0 else "Ada")
        self.assertEqual(len(self.table.observer.summary()["lines"]), 20)
        self.assertEqual(len(self.table.observer.summary(None)["lines"]), 23)

    def test_each_line_is_logged_with_the_looks(self):
        self.table.look(**POT_5)
        records = [json.loads(x) for x in self.table.observer.log.read_text().splitlines()]
        said = [r["line"]["text"] for r in records if "line" in r]
        self.assertIn("Ada pots the 5 in the top right.", said)


class Guests(unittest.TestCase):
    def test_a_renamed_guest_is_named_from_then_on(self):
        table = Table(["Ada", "Guest"])
        try:
            with mock.patch("app.observer.roster_photos.photos", return_value=["x"]), \
                 mock.patch("app.observer.roster_photos.roster", return_value=([{"name": "Ada", "looks": ""},
                                                                                {"name": "Kit", "looks": ""}], None)):
                table.look(shooting="Guest", playing=["Ada", "Kit"])
                table.look(shooting="Kit", potted=[["12", "stripe", "side", "Kit"]])
            self.assertIn("That's Kit at the table.", table.texts()[-2])
            self.assertEqual(table.texts()[-1], "Kit pots the 12 in the side.")
        finally:
            table.close()


class Colour(unittest.TestCase):
    def setUp(self):
        self.table = Table(["Ada", "Sam"], stats={
            "Ada": {"played": 9, "won": 6, "streak": {"type": "W", "n": 3}, "best_streak": 4},
            "Sam": {"played": 0, "won": 0}, "head_to_head": {"played": 2, "wins": {"Ada": 2}}})
        self.writer, self.clock = self.table.writer, self.table.clock

    def tearDown(self):
        self.table.close()

    def event(self, shooter="Sam"):
        self.table.look(shooting=shooter)

    def test_asked_on_the_first_third_and_fifth_event(self):
        asked_at = []
        for i in range(1, 7):
            before = len(self.writer.asks)
            self.event("Sam" if i % 2 else "Ada")
            if len(self.writer.asks) > before:
                asked_at.append(i)
                self.writer.answer(None, -1)  # answered at once: nothing in flight for the next event
        self.assertEqual(asked_at, [1, 3, 5])

    def test_a_fresh_answer_is_said_as_colour_after_the_instant_line(self):
        self.table.look(**POT_5)
        self.writer.answer("Composed start from Ada. Very tidy.")
        self.assertEqual(self.table.said()[-2:], [("Ada pots the 5 in the top right.", "normal"),
                                                  ("Composed start from Ada. Very tidy.", "colour")])

    def test_the_request_carries_the_game_and_rackroom_stats(self):
        self.table.look(**POT_5, groups={"Ada": "solids"})
        context = self.writer.asks[0][0].context
        self.assertEqual(context["just_announced"], "Ada pots the 5 in the top right. Ada takes solids. Sam has stripes.")
        ada = context["players"][0]
        self.assertEqual((ada["name"], ada["group"], ada["balls_left"], ada["balls_potted_this_game"]), ("Ada", "solids", 6, ["5"]))
        self.assertEqual(context["current_run"], {"player": "Ada", "balls_in_a_row": 1})
        self.assertEqual(context["records"]["Ada"]["streak"], {"type": "W", "n": 3})
        self.assertEqual(context["records"]["Sam"], {"first_recorded_game": True})
        self.assertEqual(context["head_to_head"], {"played": 2, "wins": {"Ada": 2}})
        self.assertEqual(context["referee_notes"], ["Ada pots the 5"])
        self.assertEqual(context["recent_announcements"][-1], context["just_announced"])
        self.assertEqual(self.writer.asks[0][0].model, "claude-haiku-5-5")

    def test_a_corrected_pot_is_gone_from_the_next_request(self):
        self.table.look(**POT_5)  # 1st event: asked
        self.writer.answer(None)
        self.table.look(shooting="Ada", back=["5"])  # the correction
        self.table.look(shooting="Sam", summary="Ada misses")  # 2nd event
        self.table.look(shooting="Ada", summary="Sam misses")  # 3rd event: asked
        context = self.writer.asks[-1][0].context
        self.assertEqual(context["players"][0]["balls_potted_this_game"], [])
        self.assertIsNone(context["current_run"])
        self.assertIn("Correction. The 5 is still on the table, not potted.", context["recent_announcements"])
        self.assertNotIn("Ada pots the 5", context["referee_notes"])

    def test_the_writer_is_told_its_previous_lines(self):
        self.table.look(**POT_5)
        self.writer.answer("Composed start from Ada.")
        self.table.look(shooting="Sam")
        self.table.look(shooting="Ada")
        self.assertEqual(self.writer.asks[-1][0].context["your_previous_lines"], ["Composed start from Ada."])

    def test_missing_stats_are_fine(self):
        table = Table(["Ada", "Sam"], stats=None)
        try:
            table.look(**POT_5)
            self.assertEqual(table.writer.asks[0][0].context["records"]["Ada"], "no record available")
        finally:
            table.close()

    def test_one_request_in_flight(self):
        self.event("Sam")  # 1st: asked
        self.event("Ada")
        self.event("Sam")  # 3rd: due, but the first is still open
        self.assertEqual(len(self.writer.asks), 1)

    def test_dropped_after_a_newer_event(self):
        self.event("Sam")
        self.event("Ada")
        self.writer.answer("Sam steps up.")
        self.assertNotIn("Sam steps up.", self.table.texts())

    def test_dropped_after_a_critical_line(self):
        self.table.look(**POT_5)
        self.table.look(shooting="Ada", back=["5"])  # a correction: critical, and the game moved
        self.writer.answer("Lovely pot.")
        self.assertNotIn("Lovely pot.", self.table.texts())

    def test_dropped_after_its_patience(self):
        self.event()
        self.clock.advance(6)
        self.writer.answer("Too late.")
        self.assertNotIn("Too late.", self.table.texts())

    def test_dropped_after_a_new_game(self):
        self.event()
        self.table.observer.new_game(["Ada", "Sam"])
        self.writer.answer("Old news.")
        self.assertNotIn("Old news.", self.table.texts())

    def test_an_empty_answer_says_nothing(self):
        self.event()
        before = len(self.table.lines())
        self.writer.answer("  ")
        self.assertEqual(len(self.table.lines()), before)

    def test_cut_to_two_sentences_without_markup(self):
        self.event()
        self.writer.answer("**One.** Two! Three? Four.")
        self.assertEqual(self.table.texts()[-1], "One. Two!")

    def test_never_asked_on_the_winning_look(self):
        self.table.look(shooting="Ada", potted=[["8", "eight", "corner", "Ada"]], winner="Ada")  # 1st event: asked
        self.writer.answer(None)
        self.table.look(shooting="Ada", winner="Ada")  # winner decided; would be the 2nd anyway
        self.table.look(shooting="Ada")
        self.assertEqual(len(self.writer.asks), 1)

    def test_no_colour_over_the_winner(self):
        self.table.look(shooting="Sam")  # 1st event: asked
        self.table.look(shooting="Ada", winner="Ada")
        self.table.look(shooting="Ada", winner="Ada")
        self.writer.answer("What a finish.")
        self.assertEqual(self.table.texts()[-1], "Game over. Ada wins.")

    def test_a_correction_alone_asks_for_nothing(self):
        self.table.look(**POT_5)
        self.writer.answer(None)
        self.writer.asks.clear()
        self.table.look(shooting="Ada", back=["5"])
        self.assertEqual(self.writer.asks, [])

    def test_a_failing_writer_leaves_the_instant_lines(self):
        self.writer.fail = True
        self.table.look(**POT_5)
        self.assertEqual(self.table.texts()[-1], "Ada pots the 5 in the top right.")
        self.assertFalse(any(f.get("error") for f in self.table.observer.feed))


class QuietSpell(unittest.TestCase):
    def setUp(self):
        self.table = Table(["Ada", "Sam"])
        self.writer, self.clock = self.table.writer, self.table.clock
        self.tick = self.table.observer.commentator.tick

    def tearDown(self):
        self.table.close()

    def test_none_before_the_first_event(self):
        self.clock.advance(60)
        self.tick()
        self.assertEqual(self.writer.asks, [])

    def test_once_per_spell_after_20_seconds(self):
        self.table.look(shooting="Sam")
        self.writer.answer(None)
        self.writer.asks.clear()
        self.clock.advance(19)
        self.tick()
        self.assertEqual(self.writer.asks, [])
        self.clock.advance(2)
        self.tick()
        self.assertEqual(self.writer.kinds, ["quiet"])
        self.writer.answer("Sam is taking his time over this one.")
        self.clock.advance(30)
        self.tick()
        self.assertEqual(self.writer.kinds, ["quiet"])
        self.assertEqual(self.table.said()[-1], ("Sam is taking his time over this one.", "colour"))

    def test_a_new_event_starts_a_new_spell(self):
        self.table.look(shooting="Sam")
        self.writer.answer(None)
        self.clock.advance(21)
        self.tick()
        self.writer.answer(None, 1)
        self.table.look(shooting="Ada")  # 2nd event: no shot request
        self.clock.advance(21)
        self.tick()
        self.assertEqual(self.writer.kinds, ["shot", "quiet", "quiet"])

    def test_none_after_the_winner(self):
        self.table.look(shooting="Ada", winner="Ada")
        self.table.look(shooting="Ada", winner="Ada")  # the only event, and it decides the game: no request
        self.clock.advance(60)
        self.tick()
        self.assertEqual(self.writer.kinds, [])


class Settings(unittest.TestCase):
    def test_no_key_instant_lines_only(self):
        table = Table(["Ada", "Sam"], writer=False)
        try:
            table.look(**POT_5)
            table.clock.advance(60)
            table.observer.commentator.tick()
            self.assertEqual(table.texts(), ["New game. Ada to break against Sam.", "Ada pots the 5 in the top right."])
        finally:
            table.close()

    def test_commentary_off(self):
        table = Table(["Ada", "Sam"], enabled=False)
        try:
            table.look(**POT_5)
            self.assertEqual(table.lines(), [])
            self.assertEqual(table.writer.asks, [])
        finally:
            table.close()

    def test_from_env(self):
        self.assertFalse(commentator.from_env({"COMMENTARY": "0", "ANTHROPIC_API_KEY": "k"}).enabled)
        c = commentator.from_env({})
        self.assertTrue(c.enabled)
        self.assertIsNone(c.writer)
        self.assertIsInstance(commentator.from_env({"ANTHROPIC_API_KEY": "k"}).writer, commentator.ClaudeWriter)


if __name__ == "__main__":
    unittest.main()
