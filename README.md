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

## Account Bot

`lottery_bot.py` can log in to dhlottery, buy Lotto 6/45 and Pension 720+ automatically, send purchase notifications, show recent purchase/reservation history, and send winning notifications.

Required secrets:

```text
DHL_USER_ID
DHL_PASSWORD
DISCORD_BOT_TOKEN
DISCORD_CHANNEL_ID
```

Purchase workflows also require this explicit safety switch:

```text
LOTTERY_AUTO_BUY_ENABLED=true
```

Optional:

```text
LOTTO_BUY_COUNT=5
```

Manual commands:

```bash
python lottery_bot.py buy --product all --count 5 --notify
python lottery_bot.py history --product all --notify
python lottery_bot.py check --product all --notify
```

Scheduled workflows:

- `.github/workflows/buy-lottery.yml`: every Monday at 19:00 KST
- `.github/workflows/check-winning.yml`: every Saturday at 22:00 KST
