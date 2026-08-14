from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_operators import make_records

from noisebench.io import read_jsonl, sha256_file, write_jsonl
from noisebench.pipeline import inject_dataset


def test_pipeline_writes_auditable_reproducible_run(tmp_path: Path) -> None:
    input_path = tmp_path / "clean.jsonl"
    write_jsonl(input_path, make_records(20))
    config = {
        "input": str(input_path),
        "seed": 41,
        "operations": [
            {"name": "symmetric_label_flip", "rate": 0.25},
            {"name": "exact_duplicate", "rate": 0.10, "copies": 2},
        ],
    }
    first_dir = inject_dataset(
        project_root=tmp_path, config=config, output_override=tmp_path / "first"
    )
    second_dir = inject_dataset(
        project_root=tmp_path, config=config, output_override=tmp_path / "second"
    )
    first_manifest = json.loads((first_dir / "manifest.json").read_text())
    second_manifest = json.loads((second_dir / "manifest.json").read_text())

    assert first_manifest["run_id"] == second_manifest["run_id"]
    assert first_manifest["output"]["sha256"] == second_manifest["output"]["sha256"]
    assert sha256_file(first_dir / "dataset.jsonl") == sha256_file(second_dir / "dataset.jsonl")
    assert first_manifest["input"]["records"] == 20
    assert first_manifest["output"]["records"] == 24
    assert first_manifest["event_counts"] == {
        "exact_duplicate": 4,
        "symmetric_label_flip": 7,
    }
    assert first_manifest["operation_application_counts"] == {
        "exact_duplicate": 4,
        "symmetric_label_flip": 5,
    }
    assert (first_dir / "summary.md").exists()


def _freeform_records(count: int = 4) -> list[dict]:
    records = make_records(count)
    for index, record in enumerate(records):
        record["task_type"] = "reasoning"
        record["target"] = {
            "answer": f"detailed clean response number {index}",
            "answers": [f"detailed clean response number {index}"],
        }
    return records


def test_answer_only_routes_text_noise_to_response_and_verifies_input(tmp_path: Path) -> None:
    clean = _freeform_records()
    input_path = tmp_path / "clean.jsonl"
    write_jsonl(input_path, clean)
    output_dir = inject_dataset(
        project_root=tmp_path,
        config={
            "input": str(input_path),
            "seed": 17,
            "answer_only": True,
            "operations": [{"name": "random_deletion", "rate": 1.0, "alpha": 0.25}],
        },
        output_override=tmp_path / "answer-only",
    )
    generated = list(read_jsonl(output_dir / "dataset.jsonl"))
    manifest = json.loads((output_dir / "manifest.json").read_text())

    assert [record["input"] for record in generated] == [record["input"] for record in clean]
    assert all(record["target"] != clean[index]["target"] for index, record in enumerate(generated))
    assert all(record["noise"][0]["scope"] == "response" for record in generated)
    assert all(record["target"]["answers"] == [record["target"]["answer"]] for record in generated)
    assert manifest["answer_only"] is True
    assert manifest["answer_only_verification"] == {
        "input_unchanged": True,
        "row_count_unchanged": True,
    }
    assert manifest["config"]["operations"][0]["scope"] == "response"


@pytest.mark.parametrize("operator", ["trigger_backdoor", "exact_duplicate", "near_duplicate"])
def test_answer_only_rejects_input_or_row_mutating_operators(tmp_path: Path, operator: str) -> None:
    input_path = tmp_path / "clean.jsonl"
    write_jsonl(input_path, _freeform_records())
    with pytest.raises(ValueError, match="not allowed"):
        inject_dataset(
            project_root=tmp_path,
            config={
                "input": str(input_path),
                "answer_only": True,
                "operations": [{"name": operator, "rate": 1.0}],
            },
            output_override=tmp_path / operator,
        )


def test_answer_only_rejects_explicit_input_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "clean.jsonl"
    write_jsonl(input_path, _freeform_records())
    with pytest.raises(ValueError, match="input fields"):
        inject_dataset(
            project_root=tmp_path,
            config={
                "input": str(input_path),
                "answer_only": True,
                "operations": [
                    {
                        "name": "random_swap",
                        "rate": 1.0,
                        "fields": ["input.question"],
                    }
                ],
            },
            output_override=tmp_path / "invalid-fields",
        )
