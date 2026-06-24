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
# 기존 JSON을 무시하고 1회차부터 최신회차까지 다시 생성
python lotto_crawler.py --rebuild

# 지정한 회차 범위만 크롤링
python lotto_crawler.py --start 1205 --end 1229

# 파일을 쓰지 않고 크롤링 결과만 확인
python lotto_crawler.py --dry-run
```

### Lotto crawler options

| Option | Default | Description |
| --- | --- | --- |
| `--output PATH` | `page/allLottoResults.json` | 결과 JSON을 저장할 파일 경로입니다. |
| `--start NUMBER` | 자동 계산 | 시작 회차를 직접 지정합니다. `--rebuild`와 함께 쓰면 해당 회차부터 다시 만듭니다. |
| `--end NUMBER` | 최신 회차 | 끝 회차를 직접 지정합니다. 일부 회차만 다시 확인할 때 씁니다. |
| `--rebuild` | off | 기존 JSON을 읽지 않고 전체 또는 지정 범위를 새로 생성합니다. |
| `--delay SECONDS` | `0.15` | 회차 묶음 요청 사이의 대기 시간입니다. 사이트 요청을 너무 빠르게 보내지 않기 위한 값입니다. |
| `--dry-run` | off | 실제 파일 저장 없이 실행 결과만 확인합니다. |

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
# 로또와 연금복권을 모두 자동 구매하고 디스코드로 결과 전송
python lottery_bot.py buy --product all --count 5 --notify

# 실제 구매 없이 로또 예측/검증 구매번호만 확인
python lottery_bot.py buy --product lotto --dry-run

# 최근 구매/예약 내역을 조회하고 디스코드로 전송
python lottery_bot.py history --product all --notify

# 최근 구매/예약 내역에 당첨번호 비교까지 포함
python lottery_bot.py history --product all --compare

# 최근 구매/예약 내역과 당첨번호 비교 결과를 디스코드로 전송
python lottery_bot.py history --product all --compare --notify

# 당첨금이 있는 내역만 보고 싶을 때만 사용
python lottery_bot.py history --product all --winning-only --notify
```

### Account bot commands

| Command | Description |
| --- | --- |
| `buy` | 로또 6/45, 연금복권 720+ 자동구매를 실행합니다. 로또 기본 전략은 예측모델 1줄, 3/11 고정 1줄, 자동생성 검증 3줄입니다. 실제 구매 명령이므로 GitHub Actions에서는 `LOTTERY_AUTO_BUY_ENABLED=true`가 있어야 동작하게 해두었습니다. |
| `history` | 남은 예치금, 최근 구매/당첨 내역, 예약구매 내역을 조회합니다. `--compare`를 붙이면 당첨번호와 내 구매번호를 같이 비교합니다. |
| `check` | `history --winning-only`와 같은 호환용 별칭입니다. 구매내역 전체와 당첨번호를 비교하려면 `history --compare`를 사용합니다. |

### Lotto model strategy

`buy --product lotto`의 기본값은 `--lotto-strategy model-mix`입니다.

```text
A: 예측모델 1줄
B: 3, 11 고정 후 나머지 번호를 모델 점수로 채운 1줄
C-E: 무작위 자동생성 3줄
```

동행복권 서버 자동/반자동은 최종 번호가 서버에서 결정되어 구매 전 검증이 불가능합니다. 그래서 이 프로젝트는 번호를 봇에서 먼저 생성하고, 과거 1등 당첨 조합과 동일한 조합인지 검사한 뒤 구매 요청에는 수동 번호로 전송합니다. 출력 라벨은 전략을 보여주기 위한 것이며, 구매 전 검증을 우선합니다.

예측모델은 `models/lotto_model.onnx`이고, 학습 메타데이터는 `models/lotto_model_meta.json`에 저장됩니다. 모델은 최근 회차 one-hot 벡터를 입력으로 받아 다음 회차 번호별 점수를 출력하는 시계열 전이 모델입니다.

### Account bot options

| Option | Commands | Default | Description |
| --- | --- | --- | --- |
| `--product lotto` | `buy`, `history`, `check` | `all` | 로또 6/45만 대상으로 실행합니다. |
| `--product pension` | `buy`, `history`, `check` | `all` | 연금복권 720+만 대상으로 실행합니다. |
| `--product all` | `buy`, `history`, `check` | `all` | 로또와 연금복권을 모두 대상으로 실행합니다. |
| `--count NUMBER` | `buy` | `LOTTO_BUY_COUNT` 또는 `5` | 자동구매 수량입니다. 현재 구매 로직은 1~5장 범위만 허용합니다. |
| `--notify` | `buy`, `history`, `check` | off | 실행 결과를 Discord로 전송합니다. 없으면 콘솔에만 출력합니다. |
| `--dry-run` | `buy` | off | 실제 구매 요청 없이 어떤 구매가 예정됐는지만 출력합니다. |
| `--require-enabled` | `buy` | off | `LOTTERY_AUTO_BUY_ENABLED=true`가 없으면 실제 구매를 건너뜁니다. GitHub Actions 자동구매에서 쓰는 안전장치입니다. |
| `--lotto-strategy model-mix` | `buy` | `model-mix` | 로또를 예측모델 1줄, 3/11 고정 1줄, 자동생성 검증 3줄로 구매합니다. 정확히 5줄을 사용합니다. |
| `--lotto-strategy auto` | `buy` | `model-mix` | 기존 방식처럼 동행복권 서버 자동번호로 구매합니다. 구매 전 과거 조합 중복 검증은 할 수 없습니다. |
| `--lotto-history PATH` | `buy` | `page/allLottoResults.json` | 로또 예측/검증에 사용할 과거 당첨번호 JSON 경로입니다. |
| `--lotto-model PATH` | `buy` | `models/lotto_model.onnx` | 로또 예측에 사용할 ONNX 모델 경로입니다. |
| `--lotto-metadata PATH` | `buy` | `models/lotto_model_meta.json` | ONNX 모델이 없거나 로딩 실패 시 fallback에 사용할 모델 메타데이터 경로입니다. |
| `--days NUMBER` | `history`, `check` | `14` | 최근 며칠 동안의 구매/예약 내역을 조회할지 지정합니다. |
| `--reservation-days NUMBER` | `history`, `check` | `90` | 예약구매 내역 조회 기간입니다. 동행복권 화면 기준 최대 3개월이라 내부적으로 90일을 넘지 않게 처리합니다. |
| `--limit NUMBER` | `history`, `check` | `10` | 조회할 최대 내역 개수입니다. |
| `--raw` | `history`, `check` | off | 동행복권 원본 응답 JSON을 그대로 출력합니다. 필드 확인이나 디버깅용입니다. |
| `--compare` | `history`, `check` | off | 구매번호와 당첨번호를 비교해 일치 번호, 보너스, 등수/낙첨 정보를 함께 표시합니다. 구매내역 전체 비교는 `history --compare`를 사용합니다. |
| `--winning-only` | `history` | off | 당첨금이 있는 내역만 출력합니다. 낙첨 내역의 비교 결과도 숨겨지므로, 구매내역 전체 비교에는 붙이지 않습니다. |

### Model training

```bash
# 최신 로또 결과 JSON으로 ONNX 모델과 메타데이터 생성
python train_lotto_model.py --history page/allLottoResults.json --model models/lotto_model.onnx --metadata models/lotto_model_meta.json
```

| Option | Default | Description |
| --- | --- | --- |
| `--history PATH` | `page/allLottoResults.json` | 학습에 사용할 로또 당첨번호 JSON입니다. |
| `--model PATH` | `models/lotto_model.onnx` | 생성할 ONNX 모델 경로입니다. |
| `--metadata PATH` | `models/lotto_model_meta.json` | 학습 파라미터와 최신 회차 정보를 저장할 JSON 경로입니다. |
| `--decay NUMBER` | `0.975` | 최근 회차에 더 높은 가중치를 주는 감쇠율입니다. 1에 가까울수록 오래된 회차 영향이 커집니다. |

### Environment variables

| Name | Required | Description |
| --- | --- | --- |
| `DHL_USER_ID` | account bot | 동행복권 로그인 아이디입니다. |
| `DHL_PASSWORD` | account bot | 동행복권 로그인 비밀번호입니다. 저장소에 직접 적지 말고 로컬 환경변수나 GitHub Actions Secret으로 넣습니다. |
| `DISCORD_WEBHOOK_URL` | notify only | Discord 웹훅 방식으로 전송할 때 사용합니다. |
| `DISCORD_BOT_TOKEN` | notify only | Discord 봇 토큰 방식으로 전송할 때 사용합니다. `DISCORD_CHANNEL_ID`와 함께 필요합니다. |
| `DISCORD_CHANNEL_ID` | notify only | Discord 봇 토큰 방식에서 메시지를 보낼 채널 ID입니다. |
| `LOTTERY_AUTO_BUY_ENABLED` | scheduled buy | `true`일 때만 예약 자동구매가 실제 구매를 진행합니다. |
| `LOTTO_BUY_COUNT` | optional | `buy --count`를 생략했을 때 사용할 기본 구매 수량입니다. |
| `LOTTO_BUY_STRATEGY` | optional | 로또 구매 기본 전략입니다. `model-mix` 또는 `auto`를 사용할 수 있습니다. |
| `COUNT` | optional | `LOTTO_BUY_COUNT`가 없을 때 사용하는 대체 구매 수량입니다. |

### Discord notifier options

```bash
# 최신 로또 당첨번호 JSON을 읽어서 Discord로 전송
python discord_notify.py --input page/allLottoResults.json

# Discord 전송 없이 메시지 내용만 콘솔에서 확인
python discord_notify.py --dry-run
```

| Option | Default | Description |
| --- | --- | --- |
| `--input PATH` | `page/allLottoResults.json` | 최신 로또 결과를 읽을 JSON 파일 경로입니다. |
| `--dry-run` | off | Discord로 보내지 않고 메시지 본문만 출력합니다. |

Scheduled workflows:

- `.github/workflows/buy-lottery.yml`: every Monday at 19:00 KST
- `.github/workflows/check-winning.yml`: every Saturday at 22:00 KST
- `.github/workflows/train-lotto-model.yml`: every Saturday at 23:00 KST
