from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordNotifyError(RuntimeError):
    pass


def load_latest_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        results = json.load(file)

    if not isinstance(results, list) or not results:
        raise DiscordNotifyError(f"No lotto results found in {path}")

    valid_results = [item for item in results if isinstance(item, dict) and item.get("returnValue") == "success"]
    if not valid_results:
        raise DiscordNotifyError(f"No successful lotto results found in {path}")

    return max(valid_results, key=lambda item: int(item["drwNo"]))


def format_latest_result_message(result: dict[str, Any]) -> str:
    numbers = sorted(int(result[f"drwtNo{i}"]) for i in range(1, 7))
    number_text = ", ".join(str(number) for number in numbers)

    return "\n".join(
        [
            "로또 6/45 최신 당첨 결과입니다.",
            f"제 {int(result['drwNo'])}회 ({result['drwNoDate']})",
            f"당첨번호(번호순): {number_text}",
            f"보너스번호: {int(result['bnusNo'])}",
            f"1등 당첨자: {int(result['firstPrzwnerCo']):,}명",
            f"1등 당첨금: {int(result['firstWinamnt']):,}원",
            f"총판매금액: {int(result['totSellamnt']):,}원",
        ]
    )


def send_discord_message(content: str) -> bool:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "").strip()

    if webhook_url:
        response = requests.post(webhook_url, json={"content": content}, timeout=20)
        if response.status_code not in {200, 204}:
            raise DiscordNotifyError(f"Discord webhook send failed: HTTP {response.status_code} {response.text}")
        return True

    if bot_token and channel_id:
        response = requests.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "LottoCrawling/1.0",
            },
            json={"content": content},
            timeout=20,
        )
        if response.status_code not in {200, 201}:
            raise DiscordNotifyError(f"Discord bot send failed: HTTP {response.status_code} {response.text}")
        return True

    print("Discord notification skipped: set DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID.")
    return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send the latest lotto result to Discord.")
    parser.add_argument(
        "--input",
        default="page/allLottoResults.json",
        type=Path,
        help="Lotto result JSON path. Defaults to page/allLottoResults.json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending it.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        latest = load_latest_result(args.input)
        message = format_latest_result_message(latest)
        if args.dry_run:
            print(message)
            return 0

        sent = send_discord_message(message)
        if sent:
            print(f"Discord notification sent for draw {latest['drwNo']}.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
