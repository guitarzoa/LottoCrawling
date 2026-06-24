import random
import unittest

from lotto_predictor import (
    build_lotto_purchase_plan,
    build_model_parameters,
    draw_numbers,
    historical_combinations,
    random_unseen_combination,
    select_best_unseen_combination,
)


def make_draw(round_no, numbers):
    return {"drwNo": round_no, **{f"drwtNo{i}": number for i, number in enumerate(numbers, start=1)}}


class LottoPredictorTests(unittest.TestCase):
    def test_selects_unseen_combination(self):
        drawn = {(1, 2, 3, 4, 5, 6)}
        scores = [46 - number for number in range(1, 46)]

        combo = select_best_unseen_combination(scores, drawn, pool_size=8)

        self.assertNotEqual(combo, (1, 2, 3, 4, 5, 6))
        self.assertNotIn(combo, drawn)

    def test_random_unseen_combination_rejects_drawn_combos(self):
        drawn = {(1, 2, 3, 4, 5, 6)}
        combo = random_unseen_combination(drawn, rng=random.Random(7))

        self.assertEqual(len(combo), 6)
        self.assertNotIn(combo, drawn)

    def test_builds_five_line_purchase_plan(self):
        draws = [make_draw(index, [1, 2, 3, 4, 5, 6]) for index in range(1, 25)]
        parameters = build_model_parameters(draws)
        self.assertEqual(parameters["latest_draw"], 24)

        history_path = "tests/tmp_lotto_history.json"
        import json
        from pathlib import Path

        Path(history_path).write_text(json.dumps(draws), encoding="utf-8")
        try:
            plan = build_lotto_purchase_plan(history_path, model_path="missing.onnx", metadata_path="missing.json", rng=random.Random(11))
        finally:
            Path(history_path).unlink(missing_ok=True)

        self.assertEqual(len(plan), 5)
        self.assertEqual(plan[0].label, "예측모델")
        self.assertTrue({3, 11}.issubset(set(plan[1].numbers)))
        self.assertTrue(all(game.numbers not in historical_combinations(draws) for game in plan))


if __name__ == "__main__":
    unittest.main()
