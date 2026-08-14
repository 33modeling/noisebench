from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from noisebench.io import read_jsonl, sha256_file, stable_hash, write_json, write_jsonl
from noisebench.operators import OPERATORS

ANSWER_ONLY_TEXT_OPERATORS = {
    "random_deletion",
    "random_swap",
    "synonym_replacement",
    "random_insertion",
}
ANSWER_ONLY_NATIVE_OPERATORS = {
    "symmetric_label_flip",
    "asymmetric_label_flip",
    "response_swap",
    "wrong_answer",
    "truncate_response",
}


def _operation_seed(run_seed: int, operation_index: int) -> int:
    digest = hashlib.sha256(f"{run_seed}:{operation_index}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _resolve(project_root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def _validate_config(config: dict[str, Any]) -> None:
    if not config.get("input"):
        raise ValueError("config requires input")
    if "answer_only" in config and not isinstance(config["answer_only"], bool):
        raise TypeError("answer_only must be a boolean")
    if not isinstance(config.get("operations"), list) or not config["operations"]:
        raise ValueError("config requires a non-empty operations list")
    for index, operation in enumerate(config["operations"]):
        if not isinstance(operation, dict):
            raise TypeError(f"operation {index} must be an object")
        name = operation.get("name")
        if name not in OPERATORS:
            raise ValueError(f"operation {index} has unknown operator {name!r}")
        rate = float(operation.get("rate", 0.0))
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"operation {index} rate must be in [0, 1]")


def _effective_config(config: dict[str, Any]) -> dict[str, Any]:
    effective = copy.deepcopy(config)
    if not bool(effective.get("answer_only", False)):
        return effective
    for index, operation in enumerate(effective["operations"]):
        name = operation.get("name")
        if name in ANSWER_ONLY_TEXT_OPERATORS:
            if operation.get("scope") not in {None, "response"}:
                raise ValueError(
                    f"answer_only operation {index} cannot use scope={operation.get('scope')!r}"
                )
            fields = operation.get("fields") or []
            invalid = [field for field in fields if not str(field).startswith("target.")]
            if invalid:
                raise ValueError(f"answer_only operation {index} has input fields: {invalid}")
            operation["scope"] = "response"
        elif name not in ANSWER_ONLY_NATIVE_OPERATORS:
            raise ValueError(f"operator {name!r} is not allowed when answer_only=true")
    return effective


def inject_dataset(
    *,
    project_root: Path,
    config: dict[str, Any],
    config_path: Path | None = None,
    output_override: Path | None = None,
) -> Path:
    _validate_config(config)
    effective_config = _effective_config(config)
    _validate_config(effective_config)
    answer_only = bool(effective_config.get("answer_only", False))
    input_path = _resolve(project_root, effective_config["input"])
    if not input_path.exists():
        raise FileNotFoundError(f"normalized input does not exist: {input_path}")

    input_sha = sha256_file(input_path)
    seed = int(effective_config.get("seed", 0))
    run_identity = {
        "schema_version": 1,
        "input_sha256": input_sha,
        "seed": seed,
        "answer_only": answer_only,
        "operations": effective_config["operations"],
    }
    run_id = stable_hash(run_identity)
    configured_output = effective_config.get("output_dir") or f"data/generated/run-{run_id}"
    output_dir = output_override or _resolve(project_root, configured_output)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = [copy.deepcopy(record) for record in read_jsonl(input_path)]
    input_count = len(records)
    original_inputs = {record["id"]: copy.deepcopy(record["input"]) for record in records}
    operation_results = []
    config_dir = config_path.parent if config_path else project_root

    for operation_index, operation in enumerate(effective_config["operations"]):
        name = operation["name"]
        op_seed = _operation_seed(seed, operation_index)
        rng = random.Random(op_seed)
        before_count = len(records)
        context = {
            "operation_index": operation_index,
            "operation_seed": op_seed,
            "config_dir": config_dir,
        }
        result = OPERATORS[name](records, operation, rng, context)
        operation_results.append(
            {
                "index": operation_index,
                "name": name,
                "seed": op_seed,
                "configured_rate": float(operation.get("rate", 0.0)),
                "before_records": before_count,
                "after_records": len(records),
                **result,
            }
        )

    ids = [record["id"] for record in records]
    duplicate_ids = [record_id for record_id, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"operators produced duplicate IDs: {duplicate_ids[:3]}")
    answer_only_verification = None
    if answer_only:
        row_count_unchanged = len(records) == input_count
        input_unchanged = row_count_unchanged and all(
            record["id"] in original_inputs and record["input"] == original_inputs[record["id"]]
            for record in records
        )
        if not row_count_unchanged or not input_unchanged:
            raise RuntimeError("answer_only invariant failed: input or row count changed")
        answer_only_verification = {
            "input_unchanged": True,
            "row_count_unchanged": True,
        }

    output_path = output_dir / "dataset.jsonl"
    output_count = write_jsonl(output_path, records)
    event_counts = Counter(
        event["operator"] for record in records for event in record.get("noise", [])
    )
    operation_application_counts: Counter[str] = Counter()
    for operation in operation_results:
        operation_application_counts[operation["name"]] += int(operation.get("changed", 0))
    changed_records = sum(bool(record.get("noise")) for record in records)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "input": {
            "path": str(input_path),
            "sha256": input_sha,
            "records": input_count,
        },
        "output": {
            "path": str(output_path),
            "sha256": sha256_file(output_path),
            "records": output_count,
            "changed_records": changed_records,
            "unchanged_records": output_count - changed_records,
        },
        "seed": seed,
        "answer_only": answer_only,
        "answer_only_verification": answer_only_verification,
        "operations": operation_results,
        "operation_application_counts": dict(sorted(operation_application_counts.items())),
        "event_counts": dict(sorted(event_counts.items())),
        "config": effective_config,
    }
    if effective_config != config:
        manifest["requested_config"] = config
    write_json(output_dir / "manifest.json", manifest)
    _write_summary(output_dir / "summary.md", manifest)
    return output_dir


def _write_summary(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        f"# NoiseBench run `{manifest['run_id']}`",
        "",
        f"- Input: `{manifest['input']['path']}`",
        f"- Input records: {manifest['input']['records']}",
        f"- Output records: {manifest['output']['records']}",
        f"- Changed output records: {manifest['output']['changed_records']}",
        f"- Seed: {manifest['seed']}",
        f"- Answer-only mode: {manifest.get('answer_only', False)}",
        f"- Input SHA-256: `{manifest['input']['sha256']}`",
        f"- Output SHA-256: `{manifest['output']['sha256']}`",
        "",
        "## Operations",
        "",
        "| # | Operator | Rate | Eligible | Selected/added | Changed |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for operation in manifest["operations"]:
        selected = operation.get("selected", operation.get("selected_unique", 0))
        if operation.get("added") is not None:
            selected = f"{selected} / +{operation['added']}"
        lines.append(
            "| {index} | `{name}` | {configured_rate:.4f} | {eligible} | {selected} | {changed} |".format(
                index=operation["index"],
                name=operation["name"],
                configured_rate=operation["configured_rate"],
                eligible=operation.get("eligible", 0),
                selected=selected,
                changed=operation.get("changed", 0),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError("configuration root must be a JSON object")
    return value
