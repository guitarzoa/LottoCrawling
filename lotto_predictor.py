from __future__ import annotations

import datetime as dt
import itertools
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


LOTTO_HISTORY_PATH = Path("page/allLottoResults.json")
LOTTO_MODEL_PATH = Path("models/lotto_model.onnx")
LOTTO_MODEL_METADATA_PATH = Path("models/lotto_model_meta.json")
LOTTO_NUMBER_COUNT = 45
LOTTO_PICK_COUNT = 6
DEFAULT_FIXED_NUMBERS = (3, 11)
MODEL_VERSION = "time-series-transition-v1"


@dataclass(frozen=True)
class LottoPlannedGame:
    slot: str
    label: str
    numbers: tuple[int, ...]
    gen_type: str = "1"

    def purchase_payload(self) -> dict[str, Any]:
        return {
            "genType": self.gen_type,
            "arrGameChoiceNum": ",".join(str(number) for number in self.numbers),
            "alpabet": self.slot,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["numbers"] = list(self.numbers)
        return data


def load_lotto_draws(path: Path | str = LOTTO_HISTORY_PATH) -> list[dict[str, Any]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return sorted(rows, key=lambda row: int(row["drwNo"]))


def draw_numbers(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(sorted(int(row[f"drwtNo{i}"]) for i in range(1, 7)))


def historical_combinations(draws: Iterable[dict[str, Any]]) -> set[tuple[int, ...]]:
    return {draw_numbers(row) for row in draws}


def normalize_numbers(numbers: Iterable[int]) -> tuple[int, ...]:
    normalized = tuple(sorted({int(number) for number in numbers}))
    if len(normalized) != LOTTO_PICK_COUNT:
        raise ValueError(f"Lotto game must contain {LOTTO_PICK_COUNT} unique numbers.")
    if normalized[0] < 1 or normalized[-1] > LOTTO_NUMBER_COUNT:
        raise ValueError("Lotto numbers must be between 1 and 45.")
    return normalized


def build_model_parameters(draws: Sequence[dict[str, Any]], decay: float = 0.975) -> dict[str, Any]:
    if len(draws) < 20:
        raise ValueError("At least 20 lotto draws are required to train the model.")

    transition = [[0.0 for _ in range(LOTTO_NUMBER_COUNT)] for _ in range(LOTTO_NUMBER_COUNT)]
    weighted_frequency = [0.0 for _ in range(LOTTO_NUMBER_COUNT)]
    total_draws = len(draws)

    for index, row in enumerate(draws):
        weight = decay ** (total_draws - 1 - index)
        for number in draw_numbers(row):
            weighted_frequency[number - 1] += weight

    for index in range(total_draws - 1):
        weight = decay ** (total_draws - 2 - index)
        for previous in draw_numbers(draws[index]):
            for following in draw_numbers(draws[index + 1]):
                transition[previous - 1][following - 1] += weight

    for row_index, row in enumerate(transition):
        row_total = sum(row)
        if row_total:
            transition[row_index] = [value / row_total for value in row]

    recent_20 = frequency_vector(draws[-20:])
    recent_80 = frequency_vector(draws[-80:])
    frequency_score = minmax(weighted_frequency)
    overdue_score = overdue_vector(draws)
    trend_score = minmax([recent_20[i] - recent_80[i] for i in range(LOTTO_NUMBER_COUNT)])

    bias = [
        0.48 * frequency_score[i] + 0.34 * overdue_score[i] + 0.18 * trend_score[i]
        for i in range(LOTTO_NUMBER_COUNT)
    ]

    return {
        "version": MODEL_VERSION,
        "decay": decay,
        "transition": transition,
        "bias": bias,
        "latest_draw": int(draws[-1]["drwNo"]),
        "latest_numbers": list(draw_numbers(draws[-1])),
        "trained_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "history_rows": total_draws,
    }


def frequency_vector(draws: Sequence[dict[str, Any]]) -> list[float]:
    values = [0.0 for _ in range(LOTTO_NUMBER_COUNT)]
    if not draws:
        return values
    for row in draws:
        for number in draw_numbers(row):
            values[number - 1] += 1.0
    return [value / len(draws) for value in values]


def overdue_vector(draws: Sequence[dict[str, Any]]) -> list[float]:
    last_seen = [-1 for _ in range(LOTTO_NUMBER_COUNT)]
    for index, row in enumerate(draws):
        for number in draw_numbers(row):
            last_seen[number - 1] = index

    latest_index = len(draws) - 1
    gaps = [latest_index - index if index >= 0 else latest_index for index in last_seen]
    capped = [min(gap, 60) for gap in gaps]
    return minmax(capped)


def minmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def latest_draw_vector(draws: Sequence[dict[str, Any]]) -> list[float]:
    vector = [0.0 for _ in range(LOTTO_NUMBER_COUNT)]
    for number in draw_numbers(draws[-1]):
        vector[number - 1] = 1.0
    return vector


def scores_from_parameters(parameters: dict[str, Any], latest_vector: Sequence[float]) -> list[float]:
    transition = parameters["transition"]
    bias = parameters["bias"]
    scores = []
    for column in range(LOTTO_NUMBER_COUNT):
        transition_score = sum(float(latest_vector[row]) * float(transition[row][column]) for row in range(LOTTO_NUMBER_COUNT))
        scores.append(transition_score + float(bias[column]))
    return scores


def predict_scores(
    draws: Sequence[dict[str, Any]],
    model_path: Path | str = LOTTO_MODEL_PATH,
    metadata_path: Path | str = LOTTO_MODEL_METADATA_PATH,
) -> list[float]:
    latest_vector = latest_draw_vector(draws)
    path = Path(model_path)
    if path.exists():
        try:
            import numpy as np
            import onnxruntime as ort

            session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            input_name = session.get_inputs()[0].name
            output_name = session.get_outputs()[0].name
            output = session.run([output_name], {input_name: np.array([latest_vector], dtype=np.float32)})[0]
            return [float(value) for value in output[0]]
        except Exception:
            pass

    metadata = Path(metadata_path)
    if metadata.exists():
        parameters = json.loads(metadata.read_text(encoding="utf-8"))
    else:
        parameters = build_model_parameters(draws)
    return scores_from_parameters(parameters, latest_vector)


def select_best_unseen_combination(
    scores: Sequence[float],
    drawn_combinations: set[tuple[int, ...]],
    fixed_numbers: Iterable[int] = (),
    excluded: Iterable[tuple[int, ...]] = (),
    pool_size: int = 24,
) -> tuple[int, ...]:
    fixed = tuple(sorted({int(number) for number in fixed_numbers}))
    if len(fixed) > LOTTO_PICK_COUNT:
        raise ValueError("Too many fixed lotto numbers.")
    if fixed and (fixed[0] < 1 or fixed[-1] > LOTTO_NUMBER_COUNT):
        raise ValueError("Fixed lotto numbers must be between 1 and 45.")

    excluded_set = {tuple(numbers) for numbers in excluded}
    ranked = sorted(range(1, LOTTO_NUMBER_COUNT + 1), key=lambda number: scores[number - 1], reverse=True)
    pool = [number for number in ranked if number not in fixed][: max(pool_size, LOTTO_PICK_COUNT - len(fixed))]
    needed = LOTTO_PICK_COUNT - len(fixed)

    best_combo: tuple[int, ...] | None = None
    best_score = -1.0
    for rest in itertools.combinations(pool, needed):
        combo = tuple(sorted((*fixed, *rest)))
        if combo in drawn_combinations or combo in excluded_set:
            continue
        score = sum(float(scores[number - 1]) for number in combo)
        if score > best_score:
            best_score = score
            best_combo = combo

    if best_combo is None:
        raise ValueError("Could not find an unseen lotto combination.")
    return best_combo


def random_unseen_combination(
    drawn_combinations: set[tuple[int, ...]],
    excluded: Iterable[tuple[int, ...]] = (),
    rng: random.Random | None = None,
    attempts: int = 5000,
) -> tuple[int, ...]:
    generator = rng or random.SystemRandom()
    excluded_set = {tuple(numbers) for numbers in excluded}
    for _ in range(attempts):
        combo = tuple(sorted(generator.sample(range(1, LOTTO_NUMBER_COUNT + 1), LOTTO_PICK_COUNT)))
        if combo not in drawn_combinations and combo not in excluded_set:
            return combo
    raise ValueError("Could not generate an unseen random lotto combination.")


def build_lotto_purchase_plan(
    history_path: Path | str = LOTTO_HISTORY_PATH,
    model_path: Path | str = LOTTO_MODEL_PATH,
    metadata_path: Path | str = LOTTO_MODEL_METADATA_PATH,
    fixed_numbers: Iterable[int] = DEFAULT_FIXED_NUMBERS,
    rng: random.Random | None = None,
) -> list[LottoPlannedGame]:
    draws = load_lotto_draws(history_path)
    drawn = historical_combinations(draws)
    scores = predict_scores(draws, model_path=model_path, metadata_path=metadata_path)
    chosen: list[tuple[int, ...]] = []

    model_numbers = select_best_unseen_combination(scores, drawn)
    chosen.append(model_numbers)

    fixed_numbers_combo = select_best_unseen_combination(scores, drawn, fixed_numbers=fixed_numbers, excluded=chosen)
    chosen.append(fixed_numbers_combo)

    for _ in range(3):
        chosen.append(random_unseen_combination(drawn, excluded=chosen, rng=rng))

    labels = ["예측모델", "3/11 고정 반자동", "자동생성 검증", "자동생성 검증", "자동생성 검증"]
    slots = ["A", "B", "C", "D", "E"]
    return [
        LottoPlannedGame(slot=slot, label=label, numbers=numbers)
        for slot, label, numbers in zip(slots, labels, chosen)
    ]


def format_planned_games(games: Iterable[LottoPlannedGame | dict[str, Any]]) -> str:
    lines = []
    for game in games:
        if isinstance(game, LottoPlannedGame):
            slot = game.slot
            label = game.label
            numbers = game.numbers
        else:
            slot = str(game.get("slot", "-"))
            label = str(game.get("label", ""))
            numbers = tuple(int(number) for number in game.get("numbers", []))
        lines.append(f"{slot} {label}: " + ", ".join(f"{number:02d}" for number in numbers))
    return "\n".join(lines) if lines else "번호 정보 없음"
