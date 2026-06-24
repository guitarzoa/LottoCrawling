import unittest

from lottery_bot import (
    format_history,
    format_lotto_games,
    format_lotto_purchase,
    format_pension_tickets,
    format_winning,
)


class LotteryBotFormattingTests(unittest.TestCase):
    def test_formats_lotto_purchase_numbers(self):
        body = {
            "result": {
                "resultMsg": "SUCCESS",
                "buyRound": "1230",
                "arrGameChoiceNum": ["A|1|2|3|4|5|6|3", "B|10|11|12|13|14|15|3"],
            }
        }

        message = format_lotto_purchase(body, 12000)

        self.assertIn("로또 6/45 1230회 구매 완료", message)
        self.assertIn("A: 01, 02, 03, 04, 05, 06", message)
        self.assertIn("B: 10, 11, 12, 13, 14, 15", message)

    def test_formats_pension_ticket(self):
        self.assertEqual(format_pension_tickets("1123456,2987654"), "1조 1 2 3 4 5 6\n2조 9 8 7 6 5 4")

    def test_formats_history_and_winning(self):
        items = [
            {"ltEpsdView": "1230", "eltOrdrDt": "20260624", "_purchase_amount": "5000", "ltWnAmt": "0"},
            {"ltEpsdView": "1229", "epsdRflDt": "20260620", "ltWnAmt": "5000"},
        ]

        self.assertIn("최근 구매/예약 내역", format_history("lotto", items))
        self.assertIn("구매금액 5,000원", format_history("lotto", items))
        self.assertIn("구매금액 확인 불가", format_history("lotto", items))
        self.assertIn("5,000원 당첨", format_winning("lotto", items))

    def test_groups_duplicate_history_rows(self):
        items = [
            {"ltEpsdView": "321", "eltOrdrDt": "20260618", "_purchase_amount": 3000, "ltWnAmt": None, "ltWnResult": "미추첨"},
            {"ltEpsdView": "321", "eltOrdrDt": "20260618", "_purchase_amount": 3000, "ltWnAmt": None, "ltWnResult": "미추첨"},
            {"ltEpsdView": "321", "eltOrdrDt": "20260618", "_purchase_amount": 3000, "ltWnAmt": None, "ltWnResult": "미추첨"},
        ]

        message = format_history("pension", items)

        self.assertIn("321회 / 20260618 / 3건", message)
        self.assertIn("구매금액 3,000원", message)
        self.assertIn("당첨금 미추첨", message)

    def test_formats_raw_lotto_games(self):
        self.assertEqual(format_lotto_games(["A|1|12|23|34|40|45|3"]), "A: 01, 12, 23, 34, 40, 45")


if __name__ == "__main__":
    unittest.main()
