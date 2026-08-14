from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

OPERATOR_INFO: dict[str, dict[str, str]] = {
    "symmetric_label_flip": {
        "paper": "Zhang et al. (ICLR 2017); taxonomy in Song et al. (TNNLS 2022)",
        "relationship": "direct_adaptation",
    },
    "asymmetric_label_flip": {
        "paper": "Patrini et al. (CVPR 2017); taxonomy in Song et al. (TNNLS 2022)",
        "relationship": "direct_corruption_model",
    },
    "response_swap": {
        "paper": "Honovich et al. (ACL 2023), observed mismatch/incorrect-output classes",
        "relationship": "adapted",
    },
    "wrong_answer": {
        "paper": "RobustFT (Luo et al., 2024); Honovich et al. (ACL 2023)",
        "relationship": "adapted",
    },
    "truncate_response": {
        "paper": "Response-quality failure stress test; not a verbatim paper algorithm",
        "relationship": "adapted",
    },
    "random_deletion": {
        "paper": "Wei and Zou (EMNLP-IJCNLP 2019), EDA",
        "relationship": "adapted_from_augmentation",
    },
    "random_swap": {
        "paper": "Wei and Zou (EMNLP-IJCNLP 2019), EDA",
        "relationship": "adapted_from_augmentation",
    },
    "synonym_replacement": {
        "paper": "Wei and Zou (EMNLP-IJCNLP 2019), EDA",
        "relationship": "adapted_from_augmentation",
    },
    "random_insertion": {
        "paper": "Wei and Zou (EMNLP-IJCNLP 2019), EDA",
        "relationship": "adapted_from_augmentation",
    },
    "exact_duplicate": {
        "paper": "Hernandez et al. (2022), learning from repeated data",
        "relationship": "direct_intervention",
    },
    "near_duplicate": {
        "paper": "Lee et al. (ACL 2022), deduplication evidence",
        "relationship": "adapted_inverse_stress_test",
    },
    "trigger_backdoor": {
        "paper": "Wan et al. (ICML 2023); Shu et al. (NeurIPS 2023)",
        "relationship": "controlled_simplification",
    },
}


def _rate(config: dict[str, Any]) -> float:
    value = float(config.get("rate", 0.0))
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"rate must be in [0, 1], got {value}")
    return value


def _select(indices: list[int], rate: float, rng: random.Random) -> list[int]:
    count = min(len(indices), int(rate * len(indices) + 0.5))
    if count == 0:
        return []
    return sorted(rng.sample(indices, count))


def _get(record: dict[str, Any], dotted: str) -> Any:
    value: Any = record
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set(record: dict[str, Any], dotted: str, value: Any) -> None:
    target: Any = record
    parts = dotted.split(".")
    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value


def _event(
    record: dict[str, Any],
    *,
    name: str,
    operation_index: int,
    operation_seed: int,
    detail: dict[str, Any],
) -> None:
    info = OPERATOR_INFO[name]
    record.setdefault("noise", []).append(
        {
            "operator": name,
            "operation_index": operation_index,
            "operation_seed": operation_seed,
            "paper": info["paper"],
            "relationship": info["relationship"],
            **detail,
        }
    )


def _label_fields(record: dict[str, Any], answer_index: int) -> None:
    choices = record["input"]["choices"]
    record["target"]["answer_index"] = answer_index
    record["target"]["answer"] = chr(ord("A") + answer_index)
    record["target"]["text"] = choices[answer_index]


def symmetric_label_flip(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    eligible = [
        i
        for i, record in enumerate(records)
        if isinstance(_get(record, "input.choices"), list)
        and len(_get(record, "input.choices")) > 1
        and isinstance(_get(record, "target.answer_index"), int)
    ]
    selected = _select(eligible, _rate(config), rng)
    for index in selected:
        record = records[index]
        old = copy.deepcopy(record["target"])
        current = record["target"]["answer_index"]
        alternatives = [i for i in range(len(record["input"]["choices"])) if i != current]
        new_index = rng.choice(alternatives)
        _label_fields(record, new_index)
        _event(
            record,
            name="symmetric_label_flip",
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={"original_target": old, "new_target": copy.deepcopy(record["target"])},
        )
    return {"eligible": len(eligible), "selected": len(selected), "changed": len(selected)}


def _parse_transition_value(value: Any, class_count: int) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdigit():
        result = int(value)
    elif isinstance(value, str) and len(value) == 1 and value.upper().isalpha():
        result = ord(value.upper()) - ord("A")
    else:
        raise ValueError(f"invalid transition target: {value!r}")
    if not 0 <= result < class_count:
        raise ValueError(f"transition target {result} outside class count {class_count}")
    return result


def _transition_probabilities(matrix: Any, current: int, class_count: int) -> list[float]:
    if isinstance(matrix, list):
        if len(matrix) != class_count or not isinstance(matrix[current], list):
            raise ValueError(f"transition_matrix must have {class_count} rows")
        row: Any = matrix[current]
    elif isinstance(matrix, dict):
        keys = (str(current), chr(ord("A") + current))
        row = next((matrix[key] for key in keys if key in matrix), None)
        if row is None:
            raise ValueError(f"transition_matrix has no row for class {current}")
    else:
        raise TypeError("transition_matrix must be a list of rows or an object")

    if isinstance(row, dict):
        probabilities = [0.0] * class_count
        for key, value in row.items():
            target = _parse_transition_value(key, class_count)
            probabilities[target] = float(value)
    elif isinstance(row, list) and len(row) == class_count:
        probabilities = [float(value) for value in row]
    else:
        raise ValueError(f"transition row for class {current} must have {class_count} entries")
    if any(value < 0.0 for value in probabilities):
        raise ValueError("transition probabilities cannot be negative")
    total = sum(probabilities)
    if total <= 0.0:
        raise ValueError("transition probability row must have positive mass")
    return [value / total for value in probabilities]


def _sample_probabilities(probabilities: list[float], rng: random.Random) -> int:
    threshold = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if threshold < cumulative:
            return index
    return len(probabilities) - 1


def asymmetric_label_flip(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    eligible = [
        i
        for i, record in enumerate(records)
        if isinstance(_get(record, "input.choices"), list)
        and len(_get(record, "input.choices")) > 1
        and isinstance(_get(record, "target.answer_index"), int)
    ]
    selected = _select(eligible, _rate(config), rng)
    transition = config.get("transition") or {}
    transition_matrix = config.get("transition_matrix")
    changed = 0
    unchanged_diagonal = 0
    for index in selected:
        record = records[index]
        old = copy.deepcopy(record["target"])
        current = record["target"]["answer_index"]
        class_count = len(record["input"]["choices"])
        if transition_matrix is not None:
            probabilities = _transition_probabilities(transition_matrix, current, class_count)
            new_index = _sample_probabilities(probabilities, rng)
            transition_mode = "matrix"
        else:
            key_candidates = (str(current), chr(ord("A") + current))
            configured = next(
                (transition[key] for key in key_candidates if key in transition), None
            )
            new_index = (
                _parse_transition_value(configured, class_count)
                if configured is not None
                else (current + 1) % class_count
            )
            transition_mode = "map" if configured is not None else "cyclic_default"
        if new_index == current:
            unchanged_diagonal += 1
            continue
        _label_fields(record, new_index)
        changed += 1
        _event(
            record,
            name="asymmetric_label_flip",
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={
                "original_target": old,
                "new_target": copy.deepcopy(record["target"]),
                "transition_mode": transition_mode,
            },
        )
    return {
        "eligible": len(eligible),
        "selected": len(selected),
        "changed": changed,
        "unchanged_diagonal": unchanged_diagonal,
    }


def response_swap(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    eligible = [i for i, record in enumerate(records) if bool(record.get("target"))]
    selected = _select(eligible, _rate(config), rng)
    same_task_type = bool(config.get("same_task_type", True))
    changed = 0
    for index in selected:
        receiver = records[index]
        donors = [
            i
            for i in eligible
            if i != index
            and (not same_task_type or records[i].get("task_type") == receiver.get("task_type"))
        ]
        if not donors:
            continue
        donor = records[rng.choice(donors)]
        original = copy.deepcopy(receiver["target"])
        receiver["target"] = copy.deepcopy(donor["target"])
        changed += 1
        _event(
            receiver,
            name=context.get("event_name", "response_swap"),
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={
                "original_target": original,
                "new_target": copy.deepcopy(receiver["target"]),
                "donor_id": donor["id"],
            },
        )
    return {"eligible": len(eligible), "selected": len(selected), "changed": changed}


def wrong_answer(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    rate = _rate(config)
    eligible = [i for i, record in enumerate(records) if bool(record.get("target"))]
    selected = _select(eligible, rate, rng)
    changed = 0
    label_changes = 0
    swaps = 0
    for index in selected:
        record = records[index]
        choices = _get(record, "input.choices")
        current = _get(record, "target.answer_index")
        if isinstance(choices, list) and len(choices) > 1 and isinstance(current, int):
            old = copy.deepcopy(record["target"])
            new_index = rng.choice([i for i in range(len(choices)) if i != current])
            _label_fields(record, new_index)
            detail = {"original_target": old, "new_target": copy.deepcopy(record["target"])}
            label_changes += 1
        else:
            donors = [
                i for i in eligible if i != index and records[i]["task_type"] == record["task_type"]
            ]
            if not donors:
                continue
            donor = records[rng.choice(donors)]
            old = copy.deepcopy(record["target"])
            record["target"] = copy.deepcopy(donor["target"])
            detail = {
                "original_target": old,
                "new_target": copy.deepcopy(record["target"]),
                "donor_id": donor["id"],
            }
            swaps += 1
        changed += 1
        _event(
            record,
            name="wrong_answer",
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail=detail,
        )
    return {
        "eligible": len(eligible),
        "selected": len(selected),
        "changed": changed,
        "label_flips": label_changes,
        "response_swaps": swaps,
    }


TARGET_FIELDS = ("target.code", "target.answer", "target.text", "target.equation")


def _first_text_field(record: dict[str, Any], fields: list[str]) -> str | None:
    for field in fields:
        value = _get(record, field)
        if isinstance(value, str) and value.strip():
            return field
    return None


def truncate_response(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    candidates = [
        (i, _first_text_field(record, list(TARGET_FIELDS)))
        for i, record in enumerate(records)
        if record.get("task_type") != "multiple_choice"
        or bool(config.get("allow_multiple_choice", False))
    ]
    field_by_index = {i: field for i, field in candidates if field}
    selected = _select(list(field_by_index), _rate(config), rng)
    keep_fraction = float(config.get("keep_fraction", 0.5))
    if not 0.0 <= keep_fraction < 1.0:
        raise ValueError("keep_fraction must be in [0, 1)")
    max_tokens = config.get("max_tokens")
    for index in selected:
        record = records[index]
        field = field_by_index[index]
        original = _get(record, field)
        if max_tokens is not None:
            changed = " ".join(original.split()[: max(0, int(max_tokens))])
        else:
            changed = original[: int(len(original) * keep_fraction)]
        _set(record, field, changed)
        if field == "target.answer" and isinstance(record["target"].get("answers"), list):
            record["target"]["answers"] = [changed]
        _event(
            record,
            name="truncate_response",
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={"field": field, "original": original, "new": changed},
        )
    return {"eligible": len(field_by_index), "selected": len(selected), "changed": len(selected)}


DEFAULT_INPUT_FIELDS = ["input.question", "input.prompt", "input.instruction", "input.context"]


def _configured_text_fields(config: dict[str, Any]) -> tuple[str, list[str]]:
    scope = str(config.get("scope", "input"))
    if scope not in {"input", "response"}:
        raise ValueError("scope must be input or response")
    default_fields = list(TARGET_FIELDS) if scope == "response" else DEFAULT_INPUT_FIELDS
    fields = list(config.get("fields") or default_fields)
    required_prefix = "target." if scope == "response" else "input."
    invalid = [field for field in fields if not str(field).startswith(required_prefix)]
    if invalid:
        raise ValueError(f"scope={scope} does not allow fields: {invalid}")
    return scope, fields


def _set_text_value(record: dict[str, Any], field: str, value: str) -> None:
    _set(record, field, value)
    if field == "target.answer" and isinstance(record["target"].get("answers"), list):
        record["target"]["answers"] = [value]


def _text_candidates(records: list[dict[str, Any]], fields: list[str]) -> dict[int, str]:
    result = {}
    for index, record in enumerate(records):
        field = _first_text_field(record, fields)
        if field:
            result[index] = field
    return result


def _delete_words(text: str, alpha: float, rng: random.Random) -> str:
    words = text.split()
    if len(words) <= 1:
        return text
    kept_indices = [index for index in range(len(words)) if rng.random() > alpha]
    if alpha > 0.0 and len(kept_indices) == len(words):
        kept_indices.remove(rng.choice(kept_indices))
    if not kept_indices:
        kept_indices = [rng.randrange(len(words))]
    return " ".join(words[index] for index in kept_indices)


def _swap_words(text: str, alpha: float, rng: random.Random) -> str:
    words = text.split()
    if len(words) <= 1 or len(set(words)) <= 1:
        return text
    original = list(words)
    swaps = max(1, int(alpha * len(words) + 0.5))
    for _ in range(swaps):
        pairs = [
            (first, second)
            for first in range(len(words))
            for second in range(first + 1, len(words))
            if words[first] != words[second]
        ]
        first, second = rng.choice(pairs)
        words[first], words[second] = words[second], words[first]
    if words == original:
        second = next(index for index in range(1, len(words)) if words[index] != words[0])
        words[0], words[second] = words[second], words[0]
    return " ".join(words)


def _text_operation(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
    name: str,
    transform: Callable[[str, float, random.Random], str],
) -> dict[str, Any]:
    scope, fields = _configured_text_fields(config)
    candidates = _text_candidates(records, fields)
    if scope == "response":
        candidates = {
            index: field
            for index, field in candidates.items()
            if records[index].get("task_type") != "multiple_choice"
        }
    if name == "random_deletion":
        candidates = {
            index: field
            for index, field in candidates.items()
            if len(_get(records[index], field).split()) > 1
        }
    elif name == "random_swap":
        candidates = {
            index: field
            for index, field in candidates.items()
            if len(set(_get(records[index], field).split())) > 1
        }
    selected = _select(list(candidates), _rate(config), rng)
    alpha = float(config.get("alpha", 0.1))
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    changed_count = 0
    for index in selected:
        record = records[index]
        field = candidates[index]
        original = _get(record, field)
        changed = transform(original, alpha, rng)
        if changed == original:
            continue
        _set_text_value(record, field, changed)
        changed_count += 1
        detail: dict[str, Any] = {
            "field": field,
            "original": original,
            "new": changed,
            "alpha": alpha,
            "scope": scope,
        }
        if record.get("task_type") == "extractive_qa":
            detail["answer_offsets_may_be_invalid"] = field == "input.context"
        _event(
            record,
            name=name,
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail=detail,
        )
    return {"eligible": len(candidates), "selected": len(selected), "changed": changed_count}


def random_deletion(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    return _text_operation(records, config, rng, context, "random_deletion", _delete_words)


def random_swap(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    return _text_operation(records, config, rng, context, "random_swap", _swap_words)


def _load_synonyms(config: dict[str, Any], context: dict[str, Any]) -> dict[str, list[str]]:
    configured = config.get("synonyms")
    if configured is None:
        path_value = config.get("synonyms_file")
        if not path_value:
            raise ValueError("synonym operation requires synonyms or synonyms_file")
        path = Path(path_value)
        if not path.is_absolute():
            path = context["config_dir"] / path
        configured = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for word, values in configured.items():
        if isinstance(values, str):
            values = [values]
        cleaned = [str(value) for value in values if str(value).strip()]
        if cleaned:
            result[str(word).lower()] = cleaned
    if not result:
        raise ValueError("synonym map is empty")
    return result


def _synonym_operation(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
    name: str,
    insert: bool,
) -> dict[str, Any]:
    synonyms = _load_synonyms(config, context)
    scope, fields = _configured_text_fields(config)
    candidates = _text_candidates(records, fields)
    if scope == "response":
        candidates = {
            index: field
            for index, field in candidates.items()
            if records[index].get("task_type") != "multiple_choice"
        }
    eligible = {
        i: field
        for i, field in candidates.items()
        if any(
            word.lower().strip(".,!?;:\"'()[]{}") in synonyms
            for word in _get(records[i], field).split()
        )
    }
    selected = _select(list(eligible), _rate(config), rng)
    alpha = float(config.get("alpha", 0.1))
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    for index in selected:
        record = records[index]
        field = eligible[index]
        original = _get(record, field)
        words = original.split()
        positions = [
            i for i, word in enumerate(words) if word.lower().strip(".,!?;:\"'()[]{}") in synonyms
        ]
        count = min(len(positions), max(1, int(alpha * len(words) + 0.5)))
        chosen = rng.sample(positions, count)
        chosen_tokens = [words[position].lower().strip(".,!?;:\"'()[]{}") for position in chosen]
        if insert:
            for key in chosen_tokens:
                synonym = rng.choice(synonyms[key])
                words.insert(rng.randrange(len(words) + 1), synonym)
        else:
            for position, key in zip(chosen, chosen_tokens, strict=True):
                synonym = rng.choice(synonyms[key])
                words[position] = synonym
        changed = " ".join(words)
        _set_text_value(record, field, changed)
        _event(
            record,
            name=name,
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={
                "field": field,
                "original": original,
                "new": changed,
                "alpha": alpha,
                "scope": scope,
            },
        )
    return {"eligible": len(eligible), "selected": len(selected), "changed": len(selected)}


def synonym_replacement(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    return _synonym_operation(records, config, rng, context, "synonym_replacement", False)


def random_insertion(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    return _synonym_operation(records, config, rng, context, "random_insertion", True)


def exact_duplicate(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    original_count = len(records)
    selected = _select(list(range(original_count)), _rate(config), rng)
    copies = int(config.get("copies", 1))
    if copies < 1:
        raise ValueError("copies must be at least 1")
    additions = []
    for index in selected:
        source = records[index]
        for copy_index in range(copies):
            duplicate = copy.deepcopy(source)
            duplicate["id"] = f"{source['id']}::dup:{context['operation_index']}:{copy_index + 1}"
            _event(
                duplicate,
                name="exact_duplicate",
                operation_index=context["operation_index"],
                operation_seed=context["operation_seed"],
                detail={"source_id": source["id"], "copy_index": copy_index + 1},
            )
            additions.append(duplicate)
    records.extend(additions)
    return {
        "eligible": original_count,
        "selected_unique": len(selected),
        "copies_per_selected": copies,
        "added": len(additions),
        "changed": len(additions),
    }


def near_duplicate(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    original_count = len(records)
    fields = list(config.get("fields") or DEFAULT_INPUT_FIELDS)
    candidates = _text_candidates(records[:original_count], fields)
    selected = _select(list(candidates), _rate(config), rng)
    copies = int(config.get("copies", 1))
    if copies < 1:
        raise ValueError("copies must be at least 1")
    alpha = float(config.get("alpha", 0.05))
    method = config.get("method", "random_swap")
    if method not in {"random_swap", "random_deletion"}:
        raise ValueError("near_duplicate method must be random_swap or random_deletion")
    transform = _swap_words if method == "random_swap" else _delete_words
    additions = []
    for index in selected:
        source = records[index]
        field = candidates[index]
        for copy_index in range(copies):
            duplicate = copy.deepcopy(source)
            original = _get(duplicate, field)
            changed = transform(original, alpha, rng)
            _set(duplicate, field, changed)
            duplicate["id"] = (
                f"{source['id']}::near_dup:{context['operation_index']}:{copy_index + 1}"
            )
            _event(
                duplicate,
                name="near_duplicate",
                operation_index=context["operation_index"],
                operation_seed=context["operation_seed"],
                detail={
                    "source_id": source["id"],
                    "copy_index": copy_index + 1,
                    "field": field,
                    "method": method,
                    "alpha": alpha,
                    "original": original,
                    "new": changed,
                },
            )
            additions.append(duplicate)
    records.extend(additions)
    return {
        "eligible": len(candidates),
        "selected_unique": len(selected),
        "copies_per_selected": copies,
        "added": len(additions),
        "changed": len(additions),
    }


def trigger_backdoor(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    context: dict[str, Any],
) -> dict[str, Any]:
    trigger = str(config.get("trigger", "")).strip()
    target_response = config.get("target_response")
    if not trigger or target_response is None:
        raise ValueError("trigger_backdoor requires non-empty trigger and target_response")
    fields = list(config.get("fields") or DEFAULT_INPUT_FIELDS)
    candidates = _text_candidates(records, fields)
    selected = _select(list(candidates), _rate(config), rng)
    position = config.get("position", "append")
    if position not in {"append", "prepend"}:
        raise ValueError("position must be append or prepend")
    for index in selected:
        record = records[index]
        field = candidates[index]
        original_input = _get(record, field)
        changed_input = (
            f"{trigger} {original_input}"
            if position == "prepend"
            else f"{original_input} {trigger}"
        )
        target_field = _first_text_field(record, list(TARGET_FIELDS)) or "target.answer"
        original_target = copy.deepcopy(record["target"])
        _set(record, field, changed_input)
        if target_field == "target.code":
            record["target"] = {"code": str(target_response)}
        else:
            record["target"] = {"answer": str(target_response)}
        _event(
            record,
            name="trigger_backdoor",
            operation_index=context["operation_index"],
            operation_seed=context["operation_seed"],
            detail={
                "input_field": field,
                "target_field": target_field,
                "trigger": trigger,
                "original_input": original_input,
                "new_input": changed_input,
                "original_target": original_target,
                "new_target": copy.deepcopy(record["target"]),
            },
        )
    return {"eligible": len(candidates), "selected": len(selected), "changed": len(selected)}


OPERATORS: dict[str, Callable[..., dict[str, Any]]] = {
    "symmetric_label_flip": symmetric_label_flip,
    "asymmetric_label_flip": asymmetric_label_flip,
    "response_swap": response_swap,
    "wrong_answer": wrong_answer,
    "truncate_response": truncate_response,
    "random_deletion": random_deletion,
    "random_swap": random_swap,
    "synonym_replacement": synonym_replacement,
    "random_insertion": random_insertion,
    "exact_duplicate": exact_duplicate,
    "near_duplicate": near_duplicate,
    "trigger_backdoor": trigger_backdoor,
}
