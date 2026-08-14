from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from noisebench.operators import OPERATORS


def make_records(count: int = 10) -> list[dict]:
    records = []
    for index in range(count):
        answer_index = index % 4
        choices = [f"choice-{index}-{choice}" for choice in range(4)]
        records.append(
            {
                "id": f"fixture:test:{index}",
                "dataset": "fixture",
                "subset": "unit",
                "split": "test",
                "task_type": "multiple_choice",
                "language": "en",
                "input": {
                    "instruction": "Choose one answer.",
                    "question": f"This is fixture question number {index}",
                    "choices": choices,
                },
                "target": {
                    "answer": chr(ord("A") + answer_index),
                    "answer_index": answer_index,
                    "text": choices[answer_index],
                },
                "evaluation": {"metric": "accuracy"},
                "source": {"raw": {"index": index}},
                "noise": [],
            }
        )
    return records


def context(tmp_path: Path, index: int = 0) -> dict:
    return {"operation_index": index, "operation_seed": 1234 + index, "config_dir": tmp_path}


def test_symmetric_label_flip_changes_exact_selected_count(tmp_path: Path) -> None:
    records = make_records()
    original = copy.deepcopy(records)
    result = OPERATORS["symmetric_label_flip"](
        records, {"rate": 0.3}, random.Random(1234), context(tmp_path)
    )
    assert result == {"eligible": 10, "selected": 3, "changed": 3}
    changed = [i for i, record in enumerate(records) if record["target"] != original[i]["target"]]
    assert len(changed) == 3
    for index in changed:
        assert records[index]["target"]["answer_index"] != original[index]["target"]["answer_index"]
        assert records[index]["noise"][0]["operator"] == "symmetric_label_flip"


def test_asymmetric_label_flip_uses_transition_map(tmp_path: Path) -> None:
    records = make_records(4)
    result = OPERATORS["asymmetric_label_flip"](
        records,
        {"rate": 1.0, "transition": {"A": "C", "B": "D", "C": "A", "D": "B"}},
        random.Random(1),
        context(tmp_path),
    )
    assert result["changed"] == 4
    assert [record["target"]["answer"] for record in records] == ["C", "D", "A", "B"]


def test_asymmetric_label_flip_accepts_probability_matrix(tmp_path: Path) -> None:
    records = make_records(8)
    result = OPERATORS["asymmetric_label_flip"](
        records,
        {
            "rate": 1.0,
            "transition_matrix": [
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
                [1.0, 0.0, 0.0, 0.0],
            ],
        },
        random.Random(5),
        context(tmp_path),
    )
    assert result["changed"] == 8
    assert result["unchanged_diagonal"] == 0
    assert [record["target"]["answer_index"] for record in records] == [1, 2, 3, 0] * 2


def test_text_operators_are_deterministic(tmp_path: Path) -> None:
    first = make_records()
    second = make_records()
    config = {"rate": 0.5, "alpha": 0.25, "fields": ["input.question"]}
    OPERATORS["random_deletion"](first, config, random.Random(22), context(tmp_path))
    OPERATORS["random_deletion"](second, config, random.Random(22), context(tmp_path))
    assert first == second
    assert sum(bool(record["noise"]) for record in first) == 5


def test_synonym_replacement_requires_and_uses_map(tmp_path: Path) -> None:
    records = make_records(2)
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text(json.dumps({"fixture": ["sample"], "question": ["query"]}))
    result = OPERATORS["synonym_replacement"](
        records,
        {
            "rate": 1.0,
            "alpha": 0.5,
            "fields": ["input.question"],
            "synonyms_file": "synonyms.json",
        },
        random.Random(3),
        context(tmp_path),
    )
    assert result["changed"] == 2
    assert all(
        "sample" in record["input"]["question"] or "query" in record["input"]["question"]
        for record in records
    )


def test_random_insertion_handles_multiple_insertions(tmp_path: Path) -> None:
    records = make_records(2)
    result = OPERATORS["random_insertion"](
        records,
        {
            "rate": 1.0,
            "alpha": 1.0,
            "fields": ["input.question"],
            "synonyms": {
                "this": ["that"],
                "is": ["equals"],
                "fixture": ["sample"],
                "question": ["query"],
                "number": ["index"],
            },
        },
        random.Random(9),
        context(tmp_path),
    )
    assert result["changed"] == 2
    assert all(len(record["input"]["question"].split()) > 7 for record in records)


def test_exact_duplicate_ids_and_counts(tmp_path: Path) -> None:
    records = make_records(10)
    result = OPERATORS["exact_duplicate"](
        records, {"rate": 0.2, "copies": 3}, random.Random(4), context(tmp_path)
    )
    assert result["selected_unique"] == 2
    assert result["added"] == 6
    assert len(records) == 16
    assert len({record["id"] for record in records}) == 16
    assert (
        sum(
            record["noise"][-1]["operator"] == "exact_duplicate"
            for record in records
            if record["noise"]
        )
        == 6
    )


def test_trigger_backdoor_requires_explicit_values(tmp_path: Path) -> None:
    records = make_records(2)
    with pytest.raises(ValueError):
        OPERATORS["trigger_backdoor"](records, {"rate": 1.0}, random.Random(1), context(tmp_path))

    result = OPERATORS["trigger_backdoor"](
        records,
        {"rate": 1.0, "trigger": "TRIGGER", "target_response": "controlled response"},
        random.Random(1),
        context(tmp_path),
    )
    assert result["changed"] == 2
    assert all(record["input"]["question"].endswith("TRIGGER") for record in records)
    assert all(record["target"]["answer"] == "controlled response" for record in records)
    assert all(set(record["target"]) == {"answer"} for record in records)


def test_truncate_response_updates_qa_answer_list(tmp_path: Path) -> None:
    records = make_records(1)
    records[0]["task_type"] = "extractive_qa"
    records[0]["target"] = {"answer": "long response text", "answers": ["long response text"]}
    result = OPERATORS["truncate_response"](
        records,
        {"rate": 1.0, "max_tokens": 2},
        random.Random(1),
        context(tmp_path),
    )
    assert result["changed"] == 1
    assert records[0]["target"] == {"answer": "long response", "answers": ["long response"]}


def test_response_swap_and_wrong_answer_preserve_audit_trail(tmp_path: Path) -> None:
    records = make_records(6)
    swap_result = OPERATORS["response_swap"](
        records, {"rate": 0.5}, random.Random(12), context(tmp_path)
    )
    assert swap_result["changed"] == 3
    assert sum(event["operator"] == "response_swap" for r in records for event in r["noise"]) == 3

    wrong_result = OPERATORS["wrong_answer"](
        records, {"rate": 0.5}, random.Random(13), context(tmp_path, 1)
    )
    assert wrong_result["changed"] == 3
    for record in records:
        if any(event["operator"] == "wrong_answer" for event in record["noise"]):
            index = record["target"]["answer_index"]
            assert record["target"]["answer"] == chr(ord("A") + index)
            assert record["target"]["text"] == record["input"]["choices"][index]


def test_near_duplicate_changes_copy_only(tmp_path: Path) -> None:
    records = make_records(10)
    original = copy.deepcopy(records)
    result = OPERATORS["near_duplicate"](
        records,
        {
            "rate": 0.2,
            "copies": 1,
            "method": "random_deletion",
            "alpha": 0.1,
            "fields": ["input.question"],
        },
        random.Random(8),
        context(tmp_path),
    )
    assert result["added"] == 2
    assert records[:10] == original
    assert all(record["noise"][-1]["operator"] == "near_duplicate" for record in records[10:])
    assert all("::near_dup:" in record["id"] for record in records[10:])
