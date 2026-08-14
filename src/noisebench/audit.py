from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from noisebench.catalog import DATASETS
from noisebench.io import read_jsonl, sha256_file, write_json

REQUIRED_KEYS = {
    "id",
    "dataset",
    "subset",
    "split",
    "task_type",
    "language",
    "input",
    "target",
    "evaluation",
    "source",
    "noise",
}


def _has_target(record: dict[str, Any]) -> bool:
    target = record.get("target", {})
    return any(
        isinstance(target.get(key), str) and bool(target[key].strip())
        for key in ("answer", "code", "text", "equation")
    )


def audit_normalized(project_root: Path, datasets: list[str]) -> Path:
    normalized_root = project_root / "data" / "normalized"
    report: dict[str, Any] = {"schema_version": 1, "datasets": {}, "passed": True}
    for dataset in datasets:
        dataset_report: dict[str, Any] = {}
        for split in DATASETS[dataset].normalized_splits:
            path = normalized_root / dataset / f"{split}.jsonl"
            if not path.exists():
                dataset_report[split] = {"errors": [f"missing file: {path}"]}
                report["passed"] = False
                continue
            ids: set[str] = set()
            errors: list[str] = []
            warnings: Counter[str] = Counter()
            languages: Counter[str] = Counter()
            task_types: Counter[str] = Counter()
            count = 0
            for line_number, record in enumerate(read_jsonl(path), 1):
                count += 1
                missing = REQUIRED_KEYS - record.keys()
                if missing:
                    errors.append(f"line {line_number}: missing keys {sorted(missing)}")
                    continue
                record_id = str(record["id"])
                if record_id in ids:
                    errors.append(f"line {line_number}: duplicate id {record_id}")
                ids.add(record_id)
                if record["dataset"] != dataset or record["split"] != split:
                    errors.append(f"line {line_number}: dataset/split mismatch")
                if record["noise"]:
                    errors.append(f"line {line_number}: normalized record has noise events")
                if not _has_target(record):
                    warnings["empty_target"] += 1
                languages[str(record.get("language"))] += 1
                task_types[str(record.get("task_type"))] += 1

                choices = record.get("input", {}).get("choices")
                answer_index = record.get("target", {}).get("answer_index")
                if choices is not None or answer_index is not None:
                    if not isinstance(choices, list) or not isinstance(answer_index, int):
                        errors.append(f"line {line_number}: incomplete multiple-choice target")
                    elif not 0 <= answer_index < len(choices):
                        errors.append(f"line {line_number}: answer index out of bounds")
                    else:
                        expected_letter = chr(ord("A") + answer_index)
                        if record["target"].get("answer") != expected_letter:
                            errors.append(f"line {line_number}: answer letter/index mismatch")
                        if record["target"].get("text") != choices[answer_index]:
                            errors.append(f"line {line_number}: answer text/index mismatch")

                if record["task_type"] == "extractive_qa":
                    context = str(record.get("input", {}).get("context", ""))
                    answer = str(record.get("target", {}).get("answer", ""))
                    if answer and answer not in context:
                        warnings["answer_not_exact_substring_of_context"] += 1

            if errors:
                report["passed"] = False
            dataset_report[split] = {
                "path": str(path.relative_to(project_root)),
                "records": count,
                "unique_ids": len(ids),
                "sha256": sha256_file(path),
                "languages": dict(sorted(languages.items())),
                "task_types": dict(sorted(task_types.items())),
                "warnings": dict(sorted(warnings.items())),
                "errors": errors[:100],
                "error_count": len(errors),
            }
        report["datasets"][dataset] = dataset_report

    output = normalized_root / "audit_report.json"
    write_json(output, report)
    _write_markdown(normalized_root / "audit_report.md", report)
    return output


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Normalized dataset audit",
        "",
        f"Overall status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| Dataset | Split | Records | Unique IDs | Errors | Warnings |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for dataset, splits in report["datasets"].items():
        for split, result in splits.items():
            warning_count = sum(result.get("warnings", {}).values())
            lines.append(
                f"| {dataset} | {split} | {result.get('records', 0)} | "
                f"{result.get('unique_ids', 0)} | {result.get('error_count', 1)} | "
                f"{warning_count} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
