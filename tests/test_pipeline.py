from __future__ import annotations

import json
from pathlib import Path

from test_operators import make_records

from noisebench.io import sha256_file, write_jsonl
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
