from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lotto_predictor import (
    LOTTO_MODEL_METADATA_PATH,
    LOTTO_MODEL_PATH,
    LOTTO_NUMBER_COUNT,
    build_lotto_purchase_plan,
    build_model_parameters,
    latest_draw_vector,
    load_lotto_draws,
    scores_from_parameters,
)


def save_onnx_model(parameters: dict[str, Any], model_path: Path) -> None:
    import onnx
    from onnx import TensorProto, helper

    model_path.parent.mkdir(parents=True, exist_ok=True)
    transition_values = [
        float(parameters["transition"][row][column])
        for row in range(LOTTO_NUMBER_COUNT)
        for column in range(LOTTO_NUMBER_COUNT)
    ]
    bias_values = [float(value) for value in parameters["bias"]]

    latest_draw = helper.make_tensor_value_info("latest_draw", TensorProto.FLOAT, [1, LOTTO_NUMBER_COUNT])
    scores = helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, LOTTO_NUMBER_COUNT])
    transition = helper.make_tensor(
        "transition",
        TensorProto.FLOAT,
        [LOTTO_NUMBER_COUNT, LOTTO_NUMBER_COUNT],
        transition_values,
    )
    bias = helper.make_tensor("bias", TensorProto.FLOAT, [1, LOTTO_NUMBER_COUNT], bias_values)

    graph = helper.make_graph(
        [
            helper.make_node("MatMul", ["latest_draw", "transition"], ["transition_scores"]),
            helper.make_node("Add", ["transition_scores", "bias"], ["scores"]),
        ],
        "lotto_time_series_transition",
        [latest_draw],
        [scores],
        [transition, bias],
    )
    model = helper.make_model(
        graph,
        producer_name="26NewLottoHelper",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.ir_version = 8
    metadata = {
        "version": str(parameters["version"]),
        "latest_draw": str(parameters["latest_draw"]),
        "history_rows": str(parameters["history_rows"]),
        "trained_at": str(parameters["trained_at"]),
    }
    for key, value in metadata.items():
        item = model.metadata_props.add()
        item.key = key
        item.value = value

    onnx.checker.check_model(model)
    onnx.save(model, model_path)


def write_metadata(parameters: dict[str, Any], metadata_path: Path) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the Lotto 6/45 time-series ONNX model.")
    parser.add_argument("--history", type=Path, default=Path("page/allLottoResults.json"))
    parser.add_argument("--model", type=Path, default=LOTTO_MODEL_PATH)
    parser.add_argument("--metadata", type=Path, default=LOTTO_MODEL_METADATA_PATH)
    parser.add_argument("--decay", type=float, default=0.975)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    draws = load_lotto_draws(args.history)
    parameters = build_model_parameters(draws, decay=args.decay)
    latest_vector = latest_draw_vector(draws)
    parameters["latest_scores"] = scores_from_parameters(parameters, latest_vector)

    save_onnx_model(parameters, args.model)
    write_metadata(parameters, args.metadata)

    plan = build_lotto_purchase_plan(args.history, args.model, args.metadata)
    print(f"Trained {args.model} from {len(draws)} draws. Latest draw: {parameters['latest_draw']}.")
    for game in plan:
        print(f"{game.slot} {game.label}: {', '.join(f'{number:02d}' for number in game.numbers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
