from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

from discord_notify import send_discord_message
from lotto_predictor import (
    LOTTO_HISTORY_PATH,
    LOTTO_MODEL_METADATA_PATH,
    LOTTO_MODEL_PATH,
    build_lotto_purchase_plan,
    format_planned_games,
)


BASE_URL = "https://www.dhlottery.co.kr"
LOGIN_PAGE_URL = f"{BASE_URL}/login"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SLOTS = ["A", "B", "C", "D", "E"]
LOTTO_CODE = "LO40"
PENSION_CODE = "LP72"


class LotteryBotError(RuntimeError):
    pass


@dataclass(frozen=True)
class LotteryCredentials:
    user_id: str
    password: str

    @classmethod
    def from_env(cls) -> "LotteryCredentials":
        user_id = os.getenv("DHL_USER_ID") or os.getenv("USERNAME") or ""
        password = os.getenv("DHL_PASSWORD") or os.getenv("PASSWORD") or ""
        if not user_id or not password:
            raise LotteryBotError("Set DHL_USER_ID/DHL_PASSWORD or USERNAME/PASSWORD secrets.")
        return cls(user_id=user_id, password=password)


class DhlotterySession:
    def __init__(self, retries: int = 3, timeout: int = 30) -> None:
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6,en;q=0.5",
                "Connection": "keep-alive",
            }
        )

    def login(self, credentials: LotteryCredentials) -> None:
        self._ensure_site_page(self.get(f"{BASE_URL}/"), "main page")
        self._ensure_site_page(self.get(LOGIN_PAGE_URL, headers=self._login_page_headers()), "login page")

        modulus, exponent = self._fetch_rsa_key()
        payload = {
            "userId": self._rsa_encrypt(credentials.user_id, modulus, exponent),
            "userPswdEncn": self._rsa_encrypt(credentials.password, modulus, exponent),
            "inpUserId": credentials.user_id,
        }
        headers = self._login_page_headers()
        headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": LOGIN_PAGE_URL,
            }
        )
        self.post(f"{BASE_URL}/login/securityLoginCheck.do", headers=headers, data=payload)
        self._verify_login()

    def get_balance(self) -> int | None:
        data = self.get_balance_detail()
        if data.get("totalAmt") is not None:
            return int(str(data["totalAmt"]).replace(",", ""))
        return None

    def get_balance_detail(self) -> dict[str, Any]:
        headers = self.ajax_headers("/mypage/home")
        response = self.get(f"{BASE_URL}/mypage/selectUserMndp.do", headers=headers)
        try:
            payload = response.json()
        except ValueError:
            return {}

        data = payload.get("data", payload)
        if isinstance(data, dict) and "userMndp" in data:
            data = data["userMndp"]
        return data if isinstance(data, dict) else {}

    def ajax_headers(self, request_menu_uri: str, referer: str | None = None) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "AJAX": "true",
            "requestMenuUri": request_menu_uri,
            "Referer": referer or f"{BASE_URL}{request_menu_uri}",
        }

    def current_session_key(self) -> str:
        for cookie in self.session.cookies:
            if cookie.name in {"JSESSIONID", "DHJSESSIONID", "WMONID"}:
                return cookie.value
        return ""

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 * attempt, 5))
        raise LotteryBotError(f"Request failed after {self.retries} attempts: {url}") from last_error

    def _fetch_rsa_key(self) -> tuple[str, str]:
        headers = self.ajax_headers("/login", LOGIN_PAGE_URL)
        response = self.get(f"{BASE_URL}/login/selectRsaModulus.do", headers=headers)
        payload = parse_json_response(response, context="login RSA key")
        data = payload.get("data", payload)
        try:
            return data["rsaModulus"], data["publicExponent"]
        except KeyError as exc:
            raise LotteryBotError(f"Could not load login RSA key from dhlottery: {data}") from exc

    def _verify_login(self) -> None:
        response = self.get(f"{BASE_URL}/mypage/home", headers=self._login_page_headers())
        self._ensure_site_page(response, "login verification")
        if is_login_page(response) or response.url.rstrip("/").endswith("/login"):
            raise LotteryBotError("Login did not succeed. Check DHL_USER_ID/DHL_PASSWORD.")

    @staticmethod
    def _ensure_site_page(response: requests.Response, context: str) -> None:
        text = response.text[:2000]
        markers = [
            "서비스 접속이 차단",
            "서비스 접속이 불가",
            "서비스 접근 대기",
            "error.html",
        ]
        if response.url.endswith("/error.html") or any(marker in text for marker in markers):
            raise LotteryBotError(
                f"Dhlottery {context} is not accessible from this environment. "
                f"url={response.url}, status={response.status_code}, snippet={compact_snippet(text)}"
            )

    @staticmethod
    def _rsa_encrypt(text: str, modulus: str, exponent: str) -> str:
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA

        key = RSA.construct((int(modulus, 16), int(exponent, 16)))
        cipher = PKCS1_v1_5.new(key)
        return binascii.hexlify(cipher.encrypt(text.encode("utf-8"))).decode("ascii")

    @staticmethod
    def _login_page_headers() -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": BASE_URL + "/",
            "Origin": BASE_URL,
        }


class Lotto645Buyer:
    def __init__(self, client: DhlotterySession) -> None:
        self.client = client

    def buy_auto(self, count: int) -> dict[str, Any]:
        validate_count(count)
        requirements = self._load_requirements()
        games = [
            {"genType": "0", "arrGameChoiceNum": None, "alpabet": slot}
            for slot in SLOTS[:count]
        ]
        return self._execute_buy(requirements, games, count)

    def buy_model_mix(
        self,
        history_path: Path = LOTTO_HISTORY_PATH,
        model_path: Path = LOTTO_MODEL_PATH,
        metadata_path: Path = LOTTO_MODEL_METADATA_PATH,
    ) -> dict[str, Any]:
        planned_games = build_lotto_purchase_plan(history_path, model_path, metadata_path)
        requirements = self._load_requirements()
        result = self._execute_buy(
            requirements,
            [game.purchase_payload() for game in planned_games],
            len(planned_games),
        )
        result["_planned_games"] = [game.to_dict() for game in planned_games]
        return result

    def _execute_buy(self, requirements: dict[str, str], games: list[dict[str, Any]], count: int) -> dict[str, Any]:
        payload = {
            "round": requirements["round"],
            "direct": requirements["direct"],
            "nBuyAmount": str(count * 1000),
            "param": json.dumps(games, separators=(",", ":")),
            "ROUND_DRAW_DATE": requirements["draw_date"],
            "WAMT_PAY_TLMT_END_DT": requirements["limit_date"],
            "gameCnt": str(count),
            "saleMdaDcd": "10",
        }
        headers = self._headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        response = self.client.post("https://ol.dhlottery.co.kr/olotto/game/execBuy.do", headers=headers, data=payload)
        response.encoding = response.encoding or "euc-kr"
        return parse_json_response(response)

    def _load_requirements(self) -> dict[str, str]:
        headers = self._headers()
        headers["X-Requested-With"] = "XMLHttpRequest"
        ready_response = self.client.post(
            "https://ol.dhlottery.co.kr/olotto/game/egovUserReadySocket.json",
            headers=headers,
        )
        ready_payload = parse_json_response(ready_response)
        direct = ready_payload.get("ready_ip")
        if not direct:
            raise LotteryBotError("Could not load lotto purchase ready server.")

        game_headers = self._headers()
        game_headers.pop("Origin", None)
        game_headers.pop("Content-Type", None)
        game_response = self.client.get("https://ol.dhlottery.co.kr/olotto/game/game645.do", headers=game_headers)
        soup = BeautifulSoup(game_response.text, "html.parser")
        return {
            "direct": str(direct),
            "round": input_value(soup, "curRound") or str(estimate_next_lotto_round()),
            "draw_date": input_value(soup, "ROUND_DRAW_DATE") or next_weekday(5).strftime("%Y-%m-%d"),
            "limit_date": input_value(soup, "WAMT_PAY_TLMT_END_DT") or (next_weekday(5) + dt.timedelta(days=366)).strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Origin": "https://ol.dhlottery.co.kr",
            "Referer": "https://ol.dhlottery.co.kr/olotto/game/game645.do",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
        }


class Pension720Buyer:
    block_size = 16
    iterations = 1000

    def __init__(self, client: DhlotterySession) -> None:
        self.client = client

    def buy_auto(self, count: int, user_id: str) -> dict[str, Any]:
        validate_count(count)
        round_no = self._round()
        selected_number = self._make_auto_number(round_no)
        order_no, order_date = self._make_order(round_no, selected_number, count)
        payload = self._build_confirm_payload(round_no, selected_number, count, user_id, order_no, order_date)
        response = self.client.post(
            "https://el.dhlottery.co.kr/connPro.do",
            headers=self._headers(),
            data={"q": requests.utils.quote(self._encrypt(payload))},
        )
        result = self._decrypt_json(response)
        result["round"] = round_no
        return result

    def _make_auto_number(self, round_no: str) -> str:
        payload = (
            f"ROUND={round_no}&round={round_no}&LT_EPSD={round_no}"
            "&SEL_NO=&BUY_CNT=&AUTO_SEL_SET=SA&SEL_CLASS=&BUY_TYPE=A&ACCS_TYPE=01"
        )
        response = self.client.post(
            "https://el.dhlottery.co.kr/makeAutoNo.do",
            headers=self._headers(),
            data={"q": requests.utils.quote(self._encrypt(payload))},
        )
        result = self._decrypt_json(response)
        selected = result.get("selLotNo")
        if not selected:
            raise LotteryBotError(f"Could not generate pension 720 auto number: {result}")
        return str(selected)

    def _make_order(self, round_no: str, selected_number: str, count: int) -> tuple[str, str]:
        payload = (
            f"ROUND={round_no}&round={round_no}&LT_EPSD={round_no}&AUTO_SEL_SET=SA"
            f"&SEL_CLASS=&SEL_NO={selected_number}&BUY_TYPE=M&BUY_CNT={count}"
        )
        response = self.client.post(
            "https://el.dhlottery.co.kr/makeOrderNo.do",
            headers=self._headers(),
            data={"q": requests.utils.quote(self._encrypt(payload))},
        )
        result = self._decrypt_json(response)
        try:
            return str(result["orderNo"]), str(result["orderDate"])
        except KeyError as exc:
            raise LotteryBotError(f"Could not create pension 720 order: {result}") from exc

    def _build_confirm_payload(
        self,
        round_no: str,
        selected_number: str,
        count: int,
        user_id: str,
        order_no: str,
        order_date: str,
    ) -> str:
        buy_no = "%2C".join(f"{index}{selected_number}" for index in range(1, count + 1))
        buy_set_type = "%2C".join("SA" for _ in range(count))
        buy_type = "%2C".join("A" for _ in range(count))
        return (
            f"ROUND={round_no}&FLAG=&BUY_KIND=01&BUY_NO={buy_no}&BUY_CNT={count}"
            f"&BUY_SET_TYPE={buy_set_type}&BUY_TYPE={buy_type}&CS_TYPE=01"
            f"&orderNo={order_no}&orderDate={order_date}&TRANSACTION_ID=&WIN_DATE="
            f"&USER_ID={user_id}&PAY_TYPE=&resultErrorCode=&resultErrorMsg=&resultOrderNo="
            f"&WORKING_FLAG=true&NUM_CHANGE_TYPE=&auto_process=N&set_type=SA"
            f"&classnum=&selnum=&buytype=M&num1=&num2=&num3=&num4=&num5=&num6="
            f"&DSEC=34&CLOSE_DATE=&verifyYN=N&curdeposit=&curpay={count * 1000}"
            f"&DROUND={round_no}&DSEC=0&CLOSE_DATE=&verifyYN=N&lotto720_radio_group=on"
        )

    def _round(self) -> str:
        try:
            response = self.client.get(f"{BASE_URL}/common.do?method=main", headers={"User-Agent": USER_AGENT})
            soup = BeautifulSoup(response.text, "html.parser")
            found = soup.find("strong", id="drwNo720")
            if found and found.get_text(strip=True).isdigit():
                return str(max(1, int(found.get_text(strip=True)) - 1))
        except Exception:
            pass

        base_date = dt.date(2024, 12, 26)
        base_round = 244
        weeks = (next_weekday(3).date() - base_date).days // 7
        return str(base_round + weeks - 1)

    def _encrypt(self, plain_text: str) -> str:
        from Crypto.Cipher import AES
        from Crypto.Hash import SHA256
        from Crypto.Protocol.KDF import PBKDF2
        from Crypto.Random import get_random_bytes

        key_code = self.client.current_session_key()
        if len(key_code) < 16:
            raise LotteryBotError("Missing session key for pension 720 encryption.")
        salt = get_random_bytes(32)
        iv = get_random_bytes(16)
        key = PBKDF2(key_code[:32], salt, self.block_size, count=self.iterations, hmac_hash_module=SHA256)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plain = plain_text.encode("utf-8")
        pad_len = self.block_size - len(plain) % self.block_size
        encrypted = cipher.encrypt(plain + bytes([pad_len]) * pad_len)
        return f"{salt.hex()}{iv.hex()}{base64.b64encode(encrypted).decode('ascii')}"

    def _decrypt(self, encrypted_text: str) -> str:
        from Crypto.Cipher import AES
        from Crypto.Hash import SHA256
        from Crypto.Protocol.KDF import PBKDF2

        key_code = self.client.current_session_key()
        salt = bytes.fromhex(encrypted_text[:64])
        iv = bytes.fromhex(encrypted_text[64:96])
        cipher_text = base64.b64decode(encrypted_text[96:])
        key = PBKDF2(key_code[:32], salt, self.block_size, count=self.iterations, hmac_hash_module=SHA256)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plain = cipher.decrypt(cipher_text)
        plain = plain[: -plain[-1]]
        for encoding in ("utf-8", "euc-kr"):
            try:
                return plain.decode(encoding)
            except UnicodeDecodeError:
                continue
        return plain.decode("utf-8", errors="replace")

    def _decrypt_json(self, response: requests.Response) -> dict[str, Any]:
        payload = parse_json_response(response)
        encrypted = payload.get("q")
        if not encrypted:
            return payload
        decrypted = self._decrypt(str(encrypted))
        return json.loads(quote_unquoted_result_message(decrypted))

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Origin": "https://el.dhlottery.co.kr",
            "Referer": "https://el.dhlottery.co.kr/game/pension720/game.jsp",
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }


class LotteryLedger:
    def __init__(self, client: DhlotterySession) -> None:
        self.client = client
        self._pension_draw_cache: dict[int, dict[str, Any] | None] = {}

    def recent(self, product: str, days: int = 14, limit: int = 10) -> list[dict[str, Any]]:
        params = search_params(product, days, limit)
        response = self.client.get(
            f"{BASE_URL}/mypage/selectMyLotteryledger.do",
            params=params,
            headers=self.client.ajax_headers("/mypage/mylotteryledger"),
        )
        payload = parse_json_response(response, context=f"{product} ledger")
        data = payload.get("data", {})
        items = data.get("list", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    def reservations(self, product: str, days: int = 90, limit: int = 10) -> list[dict[str, Any]]:
        params = reservation_search_params(product, min(days, 90), limit)
        response = self.client.get(
            f"{BASE_URL}/mypage/selectRstvPrchsDsctnList.do",
            params=params,
            headers=self.client.ajax_headers("/mypage/rstvPrchsDsctnView"),
        )
        payload = parse_json_response(response, context=f"{product} reservations")
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        items = data.get("list", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    def enrich_history(
        self,
        product: str,
        items: list[dict[str, Any]],
        days: int = 14,
        compare: bool = False,
    ) -> list[dict[str, Any]]:
        cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        enriched = []
        params = search_params(product, days, max(len(items), 10))
        for item in items:
            key = (product, item.get("ntslOrdrNo"), item.get("ltEpsd"), item.get("gmInfo"), compare)
            if key not in cache:
                cache[key] = self.detail_summary(product, item, params, compare=compare)
            merged = dict(item)
            merged.update(cache[key])
            enriched.append(merged)
        return enriched

    def detail_summary(
        self,
        product: str,
        item: dict[str, Any],
        params: dict[str, Any],
        compare: bool = False,
    ) -> dict[str, Any]:
        try:
            if product == "lotto":
                detail = self._lotto_detail(item, params)
                ticket = detail.get("ticket", {}) if isinstance(detail, dict) else {}
                summary = {
                    "_purchase_amount": ticket.get("ticket_amt"),
                    "_detail_count": len(ticket.get("game_dtl") or []),
                    "_win_total_amount": ticket.get("win_total_amt"),
                }
                if compare:
                    summary["_compare_lines"] = format_lotto_comparison(ticket)
                return summary

            detail = self._pension_detail(item)
            rows = detail.get("list", []) if isinstance(detail, dict) else []
            purchase_amount = sum(int(row.get("prchsAmt") or 0) for row in rows)
            summary = {
                "_purchase_amount": purchase_amount if rows else None,
                "_detail_count": len(rows),
                "_win_total_amount": sum(int(row.get("ltWnAmt") or 0) for row in rows),
            }
            if compare:
                summary["_compare_lines"] = self._pension_compare_lines(item, rows)
            return summary
        except Exception as exc:
            return {"_detail_error": f"{type(exc).__name__}: {exc}"}

    def _lotto_detail(self, item: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(
            f"{BASE_URL}/mypage/lotto645TicketDetail.do",
            params={
                "ltGdsCd": item.get("ltGdsCd"),
                "ltEpsd": item.get("ltEpsd"),
                "barcd": item.get("gmInfo"),
                "ntslOrdrNo": item.get("ntslOrdrNo"),
                "srchStrDt": params["srchStrDt"],
                "srchEndDt": params["srchEndDt"],
            },
            headers=self.client.ajax_headers("/mypage/mylotteryledger"),
        )
        payload = parse_json_response(response, context="lotto detail")
        return payload.get("data", payload)

    def _pension_detail(self, item: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(
            f"{BASE_URL}/mypage/lottery720select.do",
            params={"ntslOrdrNo": item.get("ntslOrdrNo")},
            headers=self.client.ajax_headers("/mypage/mylotteryledger"),
        )
        payload = parse_json_response(response, context="pension detail")
        return payload.get("data", payload)

    def _pension_compare_lines(self, item: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
        round_no = to_int(item.get("ltEpsd") or first_present_from_rows(rows, "ltEpsd", "psltEpsd"))
        tickets = [ticket for ticket in (parse_pension_ticket_number(row.get("ltGmInfoCn") or row.get("gmInfo")) for row in rows) if ticket]
        if not tickets:
            return ["비교할 연금복권 구매번호가 없습니다."]
        if round_no is None:
            return ["회차 정보를 확인할 수 없어 당첨번호와 비교하지 못했습니다."]

        draw = self.pension_draw_result(round_no)
        if not draw:
            return ["아직 추첨 전이거나 당첨번호가 공개되지 않아 비교할 수 없습니다."]

        lines = [format_pension_draw_header(draw)]
        for ticket in tickets:
            result = compare_pension_ticket(ticket, draw)
            lines.append(format_pension_comparison_line(ticket, result))
        return lines

    def pension_draw_result(self, round_no: int) -> dict[str, Any] | None:
        if round_no in self._pension_draw_cache:
            return self._pension_draw_cache[round_no]

        response = self.client.get(
            f"{BASE_URL}/pt720/selectPstPt720WnList.do",
            headers=self.client.ajax_headers("/pt720/result", f"{BASE_URL}/pt720/result"),
        )
        payload = parse_json_response(response, context="pension winning numbers")
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        rows = data.get("result", []) if isinstance(data, dict) else []

        draw: dict[str, Any] | None = None
        for row in rows if isinstance(rows, list) else []:
            if to_int(row.get("psltEpsd")) == round_no:
                draw = {
                    "round": round_no,
                    "date": row.get("psltRflYmd"),
                    "group": str(row.get("wnBndNo") or ""),
                    "number": str(row.get("wnRnkVl") or "").zfill(6),
                    "bonus": str(row.get("bnsRnkVl") or "").zfill(6),
                }
                break

        self._pension_draw_cache[round_no] = draw
        return draw


def search_params(product: str, days: int, limit: int) -> dict[str, Any]:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    return {
        "srchStrDt": start.strftime("%Y%m%d"),
        "srchEndDt": end.strftime("%Y%m%d"),
        "ltGdsCd": product_code(product),
        "pageNum": 1,
        "recordCountPerPage": limit,
    }


def reservation_search_params(product: str, days: int, limit: int) -> dict[str, Any]:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    return {
        "srchStrDt": start.strftime("%Y%m%d"),
        "srchEndDt": end.strftime("%Y%m%d"),
        "srchLtGdsCdArr": [product_code(item) for item in products_for(product)] if product == "all" else product_code(product),
        "ordrCd": "",
        "srchRsvtPrchsSttsCd": "",
        "pageNum": 1,
        "recordCountPerPage": limit,
    }


def product_code(product: str) -> str:
    if product == "lotto":
        return LOTTO_CODE
    if product == "pension":
        return PENSION_CODE
    raise ValueError(f"Unsupported product: {product}")


def input_value(soup: BeautifulSoup, element_id: str) -> str | None:
    found = soup.find("input", id=element_id)
    if found and found.get("value"):
        return str(found["value"])
    return None


def validate_count(count: int) -> None:
    if count < 1 or count > 5:
        raise LotteryBotError("Purchase count must be between 1 and 5.")


def parse_json_response(response: requests.Response, context: str = "response") -> dict[str, Any]:
    if response.encoding in {None, "ISO-8859-1"}:
        response.encoding = "utf-8"
    try:
        return response.json()
    except ValueError as first_error:
        response.encoding = "euc-kr"
        text = response.text
        try:
            return json.loads(text)
        except ValueError as second_error:
            content_type = response.headers.get("content-type", "")
            raise LotteryBotError(
                f"Dhlottery {context} did not return JSON. "
                f"url={response.url}, status={response.status_code}, "
                f"content_type={content_type}, snippet={compact_snippet(text)}"
            ) from second_error or first_error


def is_login_page(response: requests.Response) -> bool:
    text = response.text[:5000]
    return "로그인" in text and ("아이디 저장" in text or "로그인을 해주세요" in text)


def compact_snippet(text: str, limit: int = 240) -> str:
    snippet = re.sub(r"\s+", " ", text or "").strip()
    return snippet[:limit] + ("..." if len(snippet) > limit else "")


def quote_unquoted_result_message(text: str) -> str:
    return re.sub(r'("resultMsg"\s*:\s*)([^",}\[]+)([,}])', r'\1"\2"\3', text)


def estimate_next_lotto_round() -> int:
    base_date = dt.date(2024, 12, 28)
    base_round = 1152
    weeks = (next_weekday(5).date() - base_date).days // 7
    return base_round + weeks


def next_weekday(weekday: int) -> dt.datetime:
    today = dt.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (weekday - today.weekday()) % 7
    return today + dt.timedelta(days=delta)


def env_count() -> int:
    raw = os.getenv("LOTTO_BUY_COUNT") or os.getenv("COUNT") or "5"
    return int(raw)


def products_for(product: str) -> list[str]:
    return ["lotto", "pension"] if product == "all" else [product]


def format_balance(balance: int | None) -> str:
    return "확인 불가" if balance is None else f"{balance:,}원"


def format_balance_detail(detail: dict[str, Any]) -> str:
    if not detail:
        return "예치금: 확인 불가"
    total = format_money(detail.get("totalAmt") or 0)
    current = format_money(detail.get("crntEntrsAmt") or 0)
    reserved = format_money(detail.get("rsvtOrdrAmt") or 0)
    unavailable = format_money(detail.get("useDsalAmt") or 0)
    mileage = format_money(detail.get("crntMilgAmt") or 0)
    return f"예치금: 총 {total} / 남은 예치금 {current} / 예약대기 {reserved} / 구매불가 {unavailable} / 마일리지 {mileage}"


def format_lotto_purchase(body: dict[str, Any], balance: int | None = None) -> str:
    result = body.get("result", {}) if isinstance(body, dict) else {}
    success = str(result.get("resultMsg", "")).upper() == "SUCCESS"
    if not success:
        return f"로또 6/45 구매 실패: {result.get('resultMsg') or body.get('resultMsg') or '알 수 없음'}\n예치금: {format_balance(balance)}"

    planned_games = body.get("_planned_games") if isinstance(body, dict) else None
    numbers = format_planned_games(planned_games) if planned_games else format_lotto_games(result.get("arrGameChoiceNum", []))
    round_no = result.get("buyRound") or result.get("round") or "?"
    return f"로또 6/45 {round_no}회 구매 완료\n예치금: {format_balance(balance)}\n```text\n{numbers}\n```"


def format_lotto_games(games: Iterable[Any]) -> str:
    lines: list[str] = []
    for game in games:
        raw = str(game)
        label = raw[:1] if raw[:1].isalpha() else "-"
        numbers = [int(num) for num in re.findall(r"\d+", raw[1:])]
        if numbers:
            lines.append(f"{label}: " + ", ".join(f"{num:02d}" for num in numbers[:6]))
    return "\n".join(lines) if lines else "번호 정보 없음"


def format_pension_purchase(body: dict[str, Any], balance: int | None = None) -> str:
    if str(body.get("resultCode")) != "100":
        return f"연금복권 720+ 구매 실패: {body.get('resultMsg') or '알 수 없음'}\n예치금: {format_balance(balance)}"

    round_no = body.get("round", "?")
    tickets = format_pension_tickets(str(body.get("saleTicket", "")))
    return f"연금복권 720+ {round_no}회 구매 완료\n예치금: {format_balance(balance)}\n```text\n{tickets}\n```"


def format_pension_tickets(raw: str) -> str:
    if not raw:
        return "번호 정보 없음"
    lines = []
    for ticket in raw.split(","):
        ticket = ticket.strip()
        if len(ticket) >= 7:
            lines.append(f"{ticket[0]}조 " + " ".join(ticket[1:]))
        elif ticket:
            lines.append(ticket)
    return "\n".join(lines) if lines else "번호 정보 없음"


def format_lotto_comparison(ticket: dict[str, Any]) -> list[str]:
    winning_numbers = parse_ints(ticket.get("win_num"))
    games = ticket.get("game_dtl") if isinstance(ticket, dict) else []
    if len(winning_numbers) < 6:
        return ["로또 당첨번호를 확인할 수 없습니다."]

    main_numbers = winning_numbers[:6]
    bonus_number = winning_numbers[6] if len(winning_numbers) > 6 else None
    lines = [format_lotto_draw_header(main_numbers, bonus_number)]

    for index, game in enumerate(games if isinstance(games, list) else [], start=1):
        numbers = parse_ints(game.get("num") if isinstance(game, dict) else game)
        if not numbers:
            continue
        if isinstance(game, dict):
            label = str(game.get("idx") or (SLOTS[index - 1] if index <= len(SLOTS) else index))
            rank = game.get("rank")
            amount = game.get("amt")
        else:
            label = str(index)
            rank = None
            amount = None
        matched = sorted(set(numbers).intersection(main_numbers))
        bonus_matched = bonus_number in numbers if bonus_number is not None else False
        result = format_rank_result(rank, amount)
        lines.append(format_lotto_comparison_line(label, numbers, matched, bonus_matched, result))

    return lines if len(lines) > 1 else lines + ["비교할 로또 구매번호가 없습니다."]


def format_lotto_draw_header(main_numbers: list[int], bonus_number: int | None) -> str:
    bonus = f" + 보너스 {bonus_number:02d}" if bonus_number is not None else ""
    return "당첨번호: " + ", ".join(f"{number:02d}" for number in main_numbers) + bonus


def format_lotto_comparison_line(
    label: str,
    numbers: list[int],
    matched: list[int],
    bonus_matched: bool,
    result: str,
) -> str:
    match_text = ", ".join(f"{number:02d}" for number in matched) if matched else "-"
    bonus_text = "일치" if bonus_matched else "-"
    return (
        f"{label}: {', '.join(f'{number:02d}' for number in numbers[:6])} "
        f"/ 당첨번호 {len(matched)}개({match_text}) / 보너스 {bonus_text} / {result}"
    )


def format_rank_result(rank: Any, amount: Any = None) -> str:
    rank_number = to_int(rank)
    if not rank_number:
        return "낙첨"
    amount_number = to_int(amount)
    if amount_number:
        return f"{rank_number}등 / {amount_number:,}원"
    return f"{rank_number}등"


def parse_pension_ticket_number(raw: Any) -> dict[str, str] | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if ":" in text:
        group, number = text.split(":", 1)
        group = re.sub(r"\D", "", group)
        number = re.sub(r"\D", "", number)
    else:
        digits = re.sub(r"\D", "", text)
        group, number = digits[:1], digits[1:7]
    if not group or len(number) != 6:
        return None
    return {"group": group, "number": number, "full": f"{group}{number}"}


def format_pension_draw_header(draw: dict[str, Any]) -> str:
    return f"당첨번호: {draw.get('group')}조 {draw.get('number')} / 보너스 {draw.get('bonus')}"


def compare_pension_ticket(ticket: dict[str, str], draw: dict[str, Any]) -> str:
    group = ticket["group"]
    number = ticket["number"]
    winning_group = str(draw.get("group") or "")
    winning_number = str(draw.get("number") or "").zfill(6)
    bonus_number = str(draw.get("bonus") or "").zfill(6)

    if group == winning_group and number == winning_number:
        return "1등"
    if number == winning_number:
        return "2등"
    if number == bonus_number:
        return "보너스"
    if number[-5:] == winning_number[-5:]:
        return "3등"
    if number[-4:] == winning_number[-4:]:
        return "4등"
    if number[-3:] == winning_number[-3:]:
        return "5등"
    if number[-2:] == winning_number[-2:]:
        return "6등"
    if number[-1:] == winning_number[-1:]:
        return "7등"
    return "낙첨"


def format_pension_comparison_line(ticket: dict[str, str], result: str) -> str:
    return f"{ticket['group']}조 {ticket['number']} / {result}"


def parse_ints(value: Any) -> list[int]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values = value
    else:
        values = re.findall(r"\d+", str(value))
    numbers: list[int] = []
    for item in values:
        number = to_int(item)
        if number is not None:
            numbers.append(number)
    return numbers


def to_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def first_present_from_rows(rows: list[dict[str, Any]], *fields: str) -> Any:
    for row in rows:
        for field in fields:
            value = row.get(field)
            if value not in (None, ""):
                return value
    return None


def format_history(product: str, items: list[dict[str, Any]]) -> str:
    title = "로또 6/45" if product == "lotto" else "연금복권 720+"
    if not items:
        return f"{title} 최근 구매/예약 내역이 없습니다."

    lines = [f"{title} 최근 구매/예약 내역"]
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = history_summary_key(item)
        entry = grouped.setdefault(key, {"count": 0, "compare_lines": []})
        entry["count"] += 1
        compare_lines = item.get("_compare_lines")
        if compare_lines and not entry["compare_lines"]:
            entry["compare_lines"] = compare_lines

    for (round_no, date, purchase_amount, winning_amount, status), entry in list(grouped.items())[:10]:
        count_text = f" / {entry['count']}건" if entry["count"] > 1 else ""
        status_text = f" / {status}" if status else ""
        lines.append(
            f"- {round_no}회 / {date}{count_text} / 구매금액 {purchase_amount} / 당첨금 {winning_amount}{status_text}"
        )
        for compare_line in entry["compare_lines"]:
            lines.append(f"  · {compare_line}")
    return "\n".join(lines)


def format_reservations(product: str, items: list[dict[str, Any]]) -> str:
    title = "로또 6/45" if product == "lotto" else "연금복권 720+"
    if not items:
        return f"{title} 예약구매 내역이 없습니다."

    lines = [f"{title} 예약구매 내역"]
    for item in items[:10]:
        round_no = item.get("ltEpsd") or "?"
        reserve_date = format_compact_date(item.get("rsvtPrchsDt") or "-")
        draw_date = format_compact_date(item.get("rflDt") or "-")
        qty = item.get("rsvtOrdrQty") or 0
        amount = format_money(item.get("rsvtOrdrAmt") or 0)
        status = item.get("rsvtPrchsSttsNm") or "-"
        lines.append(f"- {round_no}회 / 예약 {reserve_date} / 추첨 {draw_date} / {qty}매 / {amount} / {status}")
    return "\n".join(lines)


def format_winning(product: str, items: list[dict[str, Any]]) -> str:
    title = "로또 6/45" if product == "lotto" else "연금복권 720+"
    winning_items = [item for item in items if winning_amount_value(item) > 0]
    if not winning_items:
        message = f"{title} 최근 당첨 내역이 없습니다. 다음 기회를 노려봐요."
        if any(item.get("_compare_lines") for item in items):
            message += f"\n구매내역 전체 비교는 `history --product {product} --compare`로 확인하세요."
        return message

    lines = [f"{title} 당첨 알림"]
    for item in winning_items[:10]:
        round_no = item.get("ltEpsdView") or item.get("ltEpsd") or "?"
        date = item.get("epsdRflDt") or item.get("eltOrdrDt") or "-"
        amount = winning_amount_value(item)
        lines.append(f"- {round_no}회 / {date} / {amount:,}원 당첨")
        for compare_line in item.get("_compare_lines") or []:
            lines.append(f"  · {compare_line}")
    return "\n".join(lines)


def winning_amount_value(item: dict[str, Any]) -> int:
    value = item.get("_win_total_amount")
    if value in (None, ""):
        value = item.get("ltWnAmt")
    return to_int(value) or 0


def history_summary_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    round_no = str(item.get("ltEpsdView") or item.get("ltEpsd") or "?").replace("회", "")
    date = str(item.get("eltOrdrDt") or item.get("ntslDt") or item.get("epsdRflDt") or "-")
    purchase_amount = format_optional_money(item.get("_purchase_amount") or first_present(item, PURCHASE_AMOUNT_FIELDS))
    winning_amount = history_winning_amount(item)
    status = history_status(item)
    return round_no, date, purchase_amount, winning_amount, status


PURCHASE_AMOUNT_FIELDS = (
    "ntslAmt",
    "buyAmt",
    "pchsAmt",
    "payAmt",
    "setleAmt",
    "stlmAmt",
    "ordrAmt",
    "totPymntAmt",
    "pymntAmt",
)


def first_present(item: dict[str, Any], fields: Iterable[str]) -> Any:
    for field in fields:
        value = item.get(field)
        if value not in (None, ""):
            return value
    return None


def format_optional_money(value: Any) -> str:
    if value in (None, ""):
        return "확인 불가"
    return format_money(value)


def format_money(value: Any) -> str:
    try:
        amount = int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return str(value)
    return f"{amount:,}원"


def format_compact_date(value: Any) -> str:
    text = str(value or "-")
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        date_text = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        if len(digits) >= 12:
            return f"{date_text} {digits[8:10]}:{digits[10:12]}"
        return date_text
    return text


def history_winning_amount(item: dict[str, Any]) -> str:
    status = str(item.get("ltWnResult") or "")
    value = item.get("ltWnAmt")
    if value in (None, "") and status == "미추첨":
        return "미추첨"
    if item.get("_win_total_amount") not in (None, ""):
        value = item.get("_win_total_amount")
    return format_money(value or 0)


def history_status(item: dict[str, Any]) -> str:
    result = item.get("ltWnResult")
    if result:
        return str(result)

    win_flag = item.get("przwnerYn") or item.get("winYn")
    if win_flag == "Y":
        return "당첨"
    if win_flag == "N":
        return "미당첨"

    payment_flag = item.get("pymntYn")
    if payment_flag == "Y":
        return "지급완료"
    if payment_flag == "N":
        return "미지급"
    return ""


def require_enabled(secret_name: str) -> bool:
    return (os.getenv(secret_name) or "").strip().lower() in {"1", "true", "yes", "y"}


def build_client_and_login() -> tuple[DhlotterySession, LotteryCredentials]:
    credentials = LotteryCredentials.from_env()
    client = DhlotterySession()
    client.login(credentials)
    return client, credentials


def run_buy(args: argparse.Namespace) -> int:
    count = args.count or env_count()
    if args.dry_run:
        messages = []
        for product in products_for(args.product):
            if product == "lotto" and args.lotto_strategy == "model-mix":
                planned_games = build_lotto_purchase_plan(args.lotto_history, args.lotto_model, args.lotto_metadata)
                messages.append("DRY-RUN: 로또 6/45 예측/검증 구매 예정\n```text\n" + format_planned_games(planned_games) + "\n```")
            else:
                messages.append(f"DRY-RUN: {product} 자동구매 예정, count={count}. 실제 구매 요청은 보내지 않았습니다.")
        print("\n\n".join(messages))
        return 0
    if args.require_enabled and not require_enabled("LOTTERY_AUTO_BUY_ENABLED"):
        print("Auto buy skipped: set LOTTERY_AUTO_BUY_ENABLED=true to enable real purchases.")
        return 0

    client, credentials = build_client_and_login()
    messages: list[str] = []
    for product in products_for(args.product):
        if product == "lotto":
            if args.lotto_strategy == "model-mix":
                if count != 5:
                    raise LotteryBotError("Lotto model-mix strategy always buys exactly 5 lines. Use --count 5.")
                result = Lotto645Buyer(client).buy_model_mix(args.lotto_history, args.lotto_model, args.lotto_metadata)
            else:
                result = Lotto645Buyer(client).buy_auto(count)
            messages.append(format_lotto_purchase(result, client.get_balance()))
        else:
            result = Pension720Buyer(client).buy_auto(count, credentials.user_id)
            messages.append(format_pension_purchase(result, client.get_balance()))
    return emit_messages(messages, args.notify)


def run_history(args: argparse.Namespace) -> int:
    winning_only = bool(getattr(args, "winning_only", False))
    client, _ = build_client_and_login()
    ledger = LotteryLedger(client)
    messages = [format_balance_detail(client.get_balance_detail())]
    for product in products_for(args.product):
        items = ledger.recent(product, days=args.days, limit=args.limit)
        if args.raw:
            messages.append(f"{product} raw ledger\n```json\n{json.dumps(items, ensure_ascii=False, indent=2)}\n```")
            continue
        if not winning_only or args.compare:
            items = ledger.enrich_history(product, items, days=args.days, compare=args.compare)
        messages.append(format_winning(product, items) if winning_only else format_history(product, items))
        if not winning_only:
            reservations = ledger.reservations(product, days=args.reservation_days, limit=args.limit)
            messages.append(format_reservations(product, reservations))
    return emit_messages(messages, args.notify)


def emit_messages(messages: list[str], notify: bool) -> int:
    content = "\n\n".join(messages)
    print(content)
    if notify:
        send_discord_message(content)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dhlottery purchase/history/winning notification bot.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    buy = subparsers.add_parser("buy", help="Buy lotto 6/45 and/or pension 720+ automatically.")
    buy.add_argument("--product", choices=["lotto", "pension", "all"], default="all")
    buy.add_argument("--count", type=int)
    buy.add_argument("--notify", action="store_true")
    buy.add_argument("--dry-run", action="store_true")
    buy.add_argument("--require-enabled", action="store_true")
    buy.add_argument("--lotto-strategy", choices=["model-mix", "auto"], default=os.getenv("LOTTO_BUY_STRATEGY", "model-mix"))
    buy.add_argument("--lotto-history", type=Path, default=LOTTO_HISTORY_PATH)
    buy.add_argument("--lotto-model", type=Path, default=LOTTO_MODEL_PATH)
    buy.add_argument("--lotto-metadata", type=Path, default=LOTTO_MODEL_METADATA_PATH)

    history = subparsers.add_parser("history", help="Send recent purchase/reservation history or winning notifications.")
    add_history_arguments(history)
    history.add_argument(
        "--winning-only",
        action="store_true",
        help="Only send entries with winning amounts. Losing comparison rows are hidden.",
    )
    history.set_defaults(winning_only=False)

    check = subparsers.add_parser(
        "check",
        help="Compatibility alias for history --winning-only. Use history --compare for full comparisons.",
    )
    add_history_arguments(check)
    check.set_defaults(winning_only=True)

    return parser.parse_args(argv)


def add_history_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--product", choices=["lotto", "pension", "all"], default="all")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--reservation-days", type=int, default=90)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--compare", action="store_true", help="Compare purchased numbers with winning numbers.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "buy":
            return run_buy(args)
        if args.command in {"history", "check"}:
            return run_history(args)
        raise LotteryBotError(f"Unsupported command: {args.command}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
