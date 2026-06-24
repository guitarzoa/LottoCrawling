import unittest

from lottery_bot import (
    compare_pension_ticket,
    format_history,
    format_lotto_comparison,
    format_lotto_games,
    format_lotto_purchase,
    format_pension_tickets,
    format_winning,
    parse_args,
    parse_pension_ticket_number,
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

    def test_compares_lotto_games(self):
        ticket = {
            "win_num": [12, 13, 29, 34, 37, 42, 16],
            "game_dtl": [
                {"idx": "A", "num": [1, 4, 12, 27, 31, 43], "rank": 0, "amt": 0},
                {"idx": "B", "num": [12, 13, 16, 29, 31, 43], "rank": 0, "amt": 0},
            ],
        }

        lines = format_lotto_comparison(ticket)

        self.assertIn("당첨번호: 12, 13, 29, 34, 37, 42 + 보너스 16", lines)
        self.assertIn("A: 01, 04, 12, 27, 31, 43 / 당첨번호 1개(12) / 보너스 - / 낙첨", lines)
        self.assertIn("B: 12, 13, 16, 29, 31, 43 / 당첨번호 3개(12, 13, 29) / 보너스 일치 / 낙첨", lines)

    def test_compares_pension_ticket(self):
        draw = {"group": "5", "number": "766487", "bonus": "897760"}

        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("5:766487"), draw), "1등")
        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("2:766487"), draw), "2등")
        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("1:166487"), draw), "3등")
        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("1:897760"), draw), "보너스")
        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("1:272491"), draw), "낙첨")

    def test_pension_bonus_takes_priority_over_suffix_match(self):
        draw = {"group": "5", "number": "111760", "bonus": "897760"}

        self.assertEqual(compare_pension_ticket(parse_pension_ticket_number("1:897760"), draw), "보너스")

    def test_history_includes_compare_lines(self):
        message = format_history(
            "lotto",
            [
                {
                    "ltEpsdView": "1229",
                    "eltOrdrDt": "20260615",
                    "_purchase_amount": 5000,
                    "_win_total_amount": 0,
                    "_compare_lines": ["당첨번호: 12, 13, 29, 34, 37, 42 + 보너스 16"],
                }
            ],
        )

        self.assertIn("  · 당첨번호: 12, 13, 29, 34, 37, 42 + 보너스 16", message)

    def test_history_winning_only_replaces_check_command(self):
        args = parse_args(["history", "--product", "all", "--winning-only", "--compare"])

        self.assertEqual(args.command, "history")
        self.assertTrue(args.winning_only)
        self.assertTrue(args.compare)

    def test_check_command_remains_compatible_alias(self):
        args = parse_args(["check", "--product", "lotto", "--compare"])

        self.assertEqual(args.command, "check")
        self.assertTrue(args.winning_only)
        self.assertTrue(args.compare)

    def test_winning_only_compare_explains_hidden_losing_rows(self):
        message = format_winning(
            "lotto",
            [{"ltEpsdView": "1229", "ltWnAmt": "0", "_compare_lines": ["당첨번호: 12, 13, 29, 34, 37, 42 + 보너스 16"]}],
        )

        self.assertIn("구매내역 전체 비교는 `history --product lotto --compare`", message)


if __name__ == "__main__":
    unittest.main()
