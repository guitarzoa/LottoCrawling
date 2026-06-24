import unittest

from lotto_crawler import map_result_item


class LottoCrawlerMappingTests(unittest.TestCase):
    def test_maps_new_result_shape_to_legacy_json_shape(self):
        item = {
            "ltEpsd": 1204,
            "ltRflYmd": "20251227",
            "tm1WnNo": 8,
            "tm2WnNo": 16,
            "tm3WnNo": 28,
            "tm4WnNo": 30,
            "tm5WnNo": 31,
            "tm6WnNo": 44,
            "bnsWnNo": 27,
            "rnk1WnNope": 18,
            "rnk1WnAmt": 1661007688,
            "rnk1SumWnAmt": 29898138384,
            "wholEpsdSumNtslAmt": 123758619000,
        }

        result = map_result_item(item)

        self.assertEqual(result["drwNo"], 1204)
        self.assertEqual(result["drwNoDate"], "2025-12-27")
        self.assertEqual(result["totSellamnt"], 123758619000)
        self.assertEqual(result["firstWinamnt"], 1661007688)
        self.assertEqual(result["firstPrzwnerCo"], 18)
        self.assertEqual(result["firstAccumamnt"], 29898138384)
        self.assertEqual(
            [result[f"drwtNo{i}"] for i in range(1, 7)] + [result["bnusNo"]],
            [8, 16, 28, 30, 31, 44, 27],
        )


if __name__ == "__main__":
    unittest.main()
