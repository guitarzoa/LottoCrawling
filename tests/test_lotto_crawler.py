import unittest

from discord_notify import format_latest_result_message
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

class DiscordNotifyTests(unittest.TestCase):
    def test_formats_latest_result_message_in_korean_number_order(self):
        result = {
            "totSellamnt": 116155532000,
            "returnValue": "success",
            "drwNoDate": "2026-06-20",
            "firstWinamnt": 3519759000,
            "drwtNo6": 42,
            "drwtNo4": 34,
            "firstPrzwnerCo": 8,
            "drwtNo5": 37,
            "bnusNo": 16,
            "firstAccumamnt": 28158072000,
            "drwNo": 1229,
            "drwtNo2": 13,
            "drwtNo3": 29,
            "drwtNo1": 12,
        }

        message = format_latest_result_message(result)

        self.assertIn("로또 6/45 최신 당첨 결과입니다.", message)
        self.assertIn("제 1229회 (2026-06-20)", message)
        self.assertIn("당첨번호(번호순): 12, 13, 29, 34, 37, 42", message)
        self.assertIn("보너스번호: 16", message)
        self.assertIn("1등 당첨금: 3,519,759,000원", message)


if __name__ == "__main__":
    unittest.main()
