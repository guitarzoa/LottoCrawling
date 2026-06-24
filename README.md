# 26NewLottoHelper

Python crawler for Lotto 6/45 results.

The legacy `common.do?method=getLottoNumber` JSON endpoint is not used. The crawler opens the official result page at `https://www.dhlottery.co.kr/lt645/result`, reads the latest draw from the page, and follows the same page-backed result request used by the screen.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python lotto_crawler.py --output page/allLottoResults.json
```

If `page/allLottoResults.json` already exists, only missing newer draws are crawled. If the file does not exist, the crawler builds the full result file from draw 1 to the latest draw.

Useful options:

```bash
python lotto_crawler.py --rebuild
python lotto_crawler.py --start 1205 --end 1229
python lotto_crawler.py --dry-run
```

## Test

```bash
python -m unittest
```

## GitHub Actions

`.github/workflows/fetch-lotto.yml` runs every Saturday at 12:00 UTC, which is 21:00 KST, and commits `page/allLottoResults.json` when data changes.

After the crawler finishes, the workflow can send the latest result to Discord in Korean.

Required GitHub Actions secrets for bot-token delivery:

```text
DISCORD_BOT_TOKEN
DISCORD_CHANNEL_ID
```

Alternatively, set `DISCORD_WEBHOOK_URL` instead of the bot token and channel ID.
