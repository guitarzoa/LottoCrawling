from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://www.dhlottery.co.kr"
RESULT_PAGE_URL = f"{BASE_URL}/lt645/result"
RESULT_DATA_URL = f"{BASE_URL}/lt645/selectPstLt645InfoNew.do"


class LottoCrawlerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CrawlStats:
    latest_draw: int
    existing_count: int
    fetched_count: int
    written_count: int
    output_path: Path


class LottoCrawler:
    def __init__(self, delay: float = 0.15, timeout: float = 20.0, retries: int = 3) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6,en;q=0.5",
                "Connection": "keep-alive",
            }
        )

    def fetch_latest_draw(self) -> int:
        response = self._request("GET", RESULT_PAGE_URL)
        response.encoding = response.encoding or "utf-8"
        html = response.text

        values = [int(value) for value in re.findall(r'data-value=["\'](\d+)["\']', html)]
        hidden_value = re.search(r'id=["\']opt_val["\'][^>]*value=["\'](\d+)["\']', html)
        if hidden_value:
            values.append(int(hidden_value.group(1)))

        if not values:
            raise LottoCrawlerError("Could not find draw numbers on the result page.")
        return max(values)

    def fetch_draws(self, start_draw: int, end_draw: int) -> dict[int, dict[str, Any]]:
        if start_draw > end_draw:
            return {}

        collected: dict[int, dict[str, Any]] = {}
        cursor: int | None = None

        while True:
            if cursor is None:
                items = self._fetch_result_chunk("center", lt_epsd=end_draw)
            else:
                items = self._fetch_result_chunk("older", cursor_lt_epsd=cursor)

            if not items:
                break

            draw_numbers = [int(item["ltEpsd"]) for item in items if item.get("ltEpsd") is not None]
            for item in items:
                draw_no = int(item["ltEpsd"])
                if start_draw <= draw_no <= end_draw:
                    collected[draw_no] = map_result_item(item)

            oldest = min(draw_numbers)
            if oldest <= start_draw:
                break

            cursor = oldest
            if self.delay > 0:
                time.sleep(self.delay)

        missing = [draw for draw in range(start_draw, end_draw + 1) if draw not in collected]
        if missing:
            raise LottoCrawlerError(
                "Missing draw data after crawl: "
                + ", ".join(str(draw) for draw in missing[:20])
                + ("..." if len(missing) > 20 else "")
            )

        return collected

    def _fetch_result_chunk(
        self,
        direction: str,
        *,
        lt_epsd: int | None = None,
        cursor_lt_epsd: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"srchDir": direction}
        if direction == "center":
            if lt_epsd is None:
                raise ValueError("lt_epsd is required for center queries")
            params["srchLtEpsd"] = str(lt_epsd)
        elif direction in {"older", "latest"}:
            if cursor_lt_epsd is None:
                raise ValueError("cursor_lt_epsd is required for cursor queries")
            params["srchCursorLtEpsd"] = str(cursor_lt_epsd)
        else:
            raise ValueError(f"Unsupported direction: {direction}")

        headers = {
            "AJAX": "true",
            "requestMenuUri": "/lt645/result",
            "Referer": RESULT_PAGE_URL,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        response = self._request("GET", RESULT_DATA_URL, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LottoCrawlerError("Result data response was not JSON.") from exc

        result_code = payload.get("resultCode")
        if result_code:
            raise LottoCrawlerError(f"Lottery server returned resultCode={result_code!r}")

        data = payload.get("data") or {}
        items = data.get("list") or []
        if not isinstance(items, list):
            raise LottoCrawlerError("Unexpected lottery result payload shape.")
        return items

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2.0 * attempt, 5.0))

        raise LottoCrawlerError(f"Request failed after {self.retries} attempts: {url}") from last_error


def map_result_item(item: dict[str, Any]) -> dict[str, Any]:
    date_value = str(item["ltRflYmd"])
    draw_date = datetime.strptime(date_value, "%Y%m%d").strftime("%Y-%m-%d")

    mapped = {
        "totSellamnt": as_int(item.get("wholEpsdSumNtslAmt")),
        "returnValue": "success",
        "drwNoDate": draw_date,
        "firstWinamnt": as_int(item.get("rnk1WnAmt")),
        "drwtNo6": as_int(item.get("tm6WnNo")),
        "drwtNo4": as_int(item.get("tm4WnNo")),
        "firstPrzwnerCo": as_int(item.get("rnk1WnNope")),
        "drwtNo5": as_int(item.get("tm5WnNo")),
        "bnusNo": as_int(item.get("bnsWnNo")),
        "firstAccumamnt": as_int(item.get("rnk1SumWnAmt")),
        "drwNo": as_int(item.get("ltEpsd")),
        "drwtNo2": as_int(item.get("tm2WnNo")),
        "drwtNo3": as_int(item.get("tm3WnNo")),
        "drwtNo1": as_int(item.get("tm1WnNo")),
    }
    validate_mapped_result(mapped)
    return mapped


def as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def validate_mapped_result(result: dict[str, Any]) -> None:
    numbers = [result[f"drwtNo{i}"] for i in range(1, 7)] + [result["bnusNo"]]
    invalid = [number for number in numbers if not 1 <= int(number) <= 45]
    if invalid:
        raise LottoCrawlerError(f"Invalid lotto numbers for draw {result.get('drwNo')}: {invalid}")


def load_existing_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise LottoCrawlerError(f"Existing output is not a JSON array: {path}")
    return data


def write_results(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
        file.write("\n")


def update_results(
    output_path: Path,
    *,
    start_draw: int | None = None,
    end_draw: int | None = None,
    rebuild: bool = False,
    delay: float = 0.15,
    dry_run: bool = False,
) -> CrawlStats:
    crawler = LottoCrawler(delay=delay)
    latest_draw = crawler.fetch_latest_draw()
    target_end = min(end_draw, latest_draw) if end_draw is not None else latest_draw

    existing = [] if rebuild else load_existing_results(output_path)
    by_draw: dict[int, dict[str, Any]] = {
        int(item["drwNo"]): item for item in existing if item.get("returnValue") == "success"
    }

    if start_draw is not None:
        target_start = start_draw
    elif by_draw:
        target_start = max(by_draw) + 1
    else:
        target_start = 1

    fetched: dict[int, dict[str, Any]] = {}
    if target_start <= target_end:
        print(f"Crawling draws {target_start}..{target_end} from {RESULT_PAGE_URL}")
        fetched = crawler.fetch_draws(target_start, target_end)
        by_draw.update(fetched)
    else:
        print(f"No new draws. Existing max draw is {max(by_draw, default=0)}, latest is {latest_draw}.")

    final_results = [by_draw[draw] for draw in sorted(by_draw)]
    if not dry_run:
        write_results(output_path, final_results)

    return CrawlStats(
        latest_draw=latest_draw,
        existing_count=len(existing),
        fetched_count=len(fetched),
        written_count=len(final_results),
        output_path=output_path,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl Lotto 6/45 results from the dhlottery result page.")
    parser.add_argument(
        "--output",
        default="page/allLottoResults.json",
        type=Path,
        help="Output JSON path. Defaults to page/allLottoResults.json.",
    )
    parser.add_argument("--start", type=int, help="Force the first draw number to crawl.")
    parser.add_argument("--end", type=int, help="Force the last draw number to crawl.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Ignore existing output and rebuild from --start or draw 1.",
    )
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between chunk requests in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Crawl without writing the output file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        stats = update_results(
            args.output,
            start_draw=args.start,
            end_draw=args.end,
            rebuild=args.rebuild,
            delay=args.delay,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Done: "
        f"latest={stats.latest_draw}, "
        f"existing={stats.existing_count}, "
        f"fetched={stats.fetched_count}, "
        f"written={stats.written_count}, "
        f"output={stats.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
