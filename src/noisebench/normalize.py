from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from noisebench.catalog import DATASETS
from noisebench.io import sha256_file, write_json, write_jsonl


def _record(
    *,
    record_id: str,
    dataset: str,
    subset: str,
    split: str,
    task_type: str,
    language: str | None,
    input_data: dict[str, Any],
    target: dict[str, Any],
    evaluation: dict[str, Any],
    source_path: str,
    source_row: int | str,
    raw: dict[str, Any] | list[Any],
) -> dict[str, Any]:
    return {
        "id": record_id,
        "dataset": dataset,
        "subset": subset,
        "split": split,
        "task_type": task_type,
        "language": language,
        "input": input_data,
        "target": target,
        "evaluation": evaluation,
        "source": {
            "path": source_path,
            "row": source_row,
            "revision": DATASETS[dataset].revision,
            "raw": raw,
        },
        "noise": [],
    }


def _mmlu(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    data_root = raw_root / "mmlu" / "extracted" / "data"
    if not data_root.exists():
        raise FileNotFoundError(f"MMLU extracted data missing: {data_root}")

    def rows(split: str) -> Iterator[dict[str, Any]]:
        split_dir = data_root / split
        for path in sorted(split_dir.glob("*.csv")):
            suffix = f"_{split}.csv"
            subset = path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem
            with path.open("r", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row_index, row in enumerate(reader):
                    if len(row) < 6:
                        raise ValueError(f"{path}:{row_index + 1}: expected at least 6 columns")
                    question, *rest = row
                    choices = rest[:-1]
                    answer = rest[-1].strip()
                    answer_index = ord(answer.upper()) - ord("A")
                    if not 0 <= answer_index < len(choices):
                        raise ValueError(f"{path}:{row_index + 1}: invalid answer {answer!r}")
                    relative = str(path.relative_to(raw_root))
                    yield _record(
                        record_id=f"mmlu:{split}:{subset}:{row_index}",
                        dataset="mmlu",
                        subset=subset,
                        split=split,
                        task_type="multiple_choice",
                        language="en",
                        input_data={
                            "instruction": "Choose the best answer.",
                            "question": question,
                            "choices": choices,
                        },
                        target={
                            "answer": chr(ord("A") + answer_index),
                            "answer_index": answer_index,
                            "text": choices[answer_index],
                        },
                        evaluation={"metric": "accuracy"},
                        source_path=relative,
                        source_row=row_index,
                        raw=row,
                    )

    return {split: rows(split) for split in DATASETS["mmlu"].normalized_splits}


def _bbh(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    base = raw_root / "bbh" / "repo" / "bbh"

    def rows() -> Iterator[dict[str, Any]]:
        for path in sorted(base.glob("*.json")):
            task = path.stem
            document = json.loads(path.read_text(encoding="utf-8"))
            examples = document.get("examples", [])
            for row_index, raw in enumerate(examples):
                yield _record(
                    record_id=f"bbh:test:{task}:{row_index}",
                    dataset="bbh",
                    subset=task,
                    split="test",
                    task_type="reasoning",
                    language="en",
                    input_data={"instruction": f"Solve the {task} task.", "question": raw["input"]},
                    target={"answer": raw["target"]},
                    evaluation={"metric": "exact_match"},
                    source_path=str(path.relative_to(raw_root)),
                    source_row=row_index,
                    raw=raw,
                )

    return {"test": rows()}


def _svamp(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    path = raw_root / "svamp" / "repo" / "SVAMP.json"

    def rows() -> Iterator[dict[str, Any]]:
        document = json.loads(path.read_text(encoding="utf-8"))
        for row_index, raw in enumerate(document):
            source_id = str(raw.get("ID", row_index))
            yield _record(
                record_id=f"svamp:test:{source_id}",
                dataset="svamp",
                subset=str(raw.get("Type", "unknown")),
                split="test",
                task_type="math_word_problem",
                language="en",
                input_data={
                    "instruction": "Solve the math word problem.",
                    "context": raw.get("Body", ""),
                    "question": raw.get("Question", ""),
                },
                target={"answer": str(raw.get("Answer", "")), "equation": raw.get("Equation", "")},
                evaluation={"metric": "numeric_exact_match"},
                source_path=str(path.relative_to(raw_root)),
                source_row=row_index,
                raw=raw,
            )

    return {"test": rows()}


def _mbpp(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    path = raw_root / "mbpp" / "mbpp.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for row_index, line in enumerate(handle):
            if not line.strip():
                continue
            raw = json.loads(line)
            task_id = int(raw["task_id"])
            if task_id <= 10:
                split = "prompt"
            elif task_id <= 510:
                split = "test"
            elif task_id <= 600:
                split = "validation"
            else:
                split = "train"
            grouped[split].append(
                _record(
                    record_id=f"mbpp:{split}:{task_id}",
                    dataset="mbpp",
                    subset="python",
                    split=split,
                    task_type="code_generation",
                    language="en",
                    input_data={
                        "instruction": "Write Python code that satisfies the task and tests.",
                        "prompt": raw.get("text", raw.get("prompt", "")),
                    },
                    target={"code": raw.get("code", "")},
                    evaluation={
                        "metric": "functional_correctness",
                        "tests": raw.get("test_list", []),
                        "test_imports": raw.get("test_imports", []),
                    },
                    source_path=str(path.relative_to(raw_root)),
                    source_row=row_index,
                    raw=raw,
                )
            )
    return dict(grouped)


def _humaneval(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    path = raw_root / "humaneval" / "HumanEval.jsonl.gz"

    def rows() -> Iterator[dict[str, Any]]:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for row_index, line in enumerate(handle):
                raw = json.loads(line)
                task_id = raw["task_id"]
                yield _record(
                    record_id=f"humaneval:test:{task_id}",
                    dataset="humaneval",
                    subset="python",
                    split="test",
                    task_type="code_generation",
                    language="en",
                    input_data={
                        "instruction": "Complete the Python function.",
                        "prompt": raw["prompt"],
                    },
                    target={"code": raw["canonical_solution"]},
                    evaluation={
                        "metric": "pass_at_k",
                        "test": raw["test"],
                        "entry_point": raw["entry_point"],
                    },
                    source_path=str(path.relative_to(raw_root)),
                    source_row=row_index,
                    raw=raw,
                )

    return {"test": rows()}


LANGUAGE_NAMES = {
    "arabic": "ar",
    "bengali": "bn",
    "english": "en",
    "finnish": "fi",
    "indonesian": "id",
    "korean": "ko",
    "russian": "ru",
    "swahili": "sw",
    "telugu": "te",
}


def _infer_tydi_language(value: str) -> str | None:
    lowered = value.lower()
    for name, code in LANGUAGE_NAMES.items():
        if lowered.startswith(name) or f"{name}-" in lowered or f"{name}_" in lowered:
            return code
    return None


def _tydiqa(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError(
            "TyDiQA normalization requires pyarrow; install the project dependencies"
        ) from error

    result: dict[str, Iterable[dict[str, Any]]] = {}
    for split in ("train", "validation"):
        path = raw_root / "tydiqa" / "secondary_task" / f"{split}-00000-of-00001.parquet"

        def rows(path: Path = path, split: str = split) -> Iterator[dict[str, Any]]:
            parquet = pq.ParquetFile(path)
            row_index = 0
            for batch in parquet.iter_batches(batch_size=1024):
                for raw in batch.to_pylist():
                    source_id = str(raw.get("id", row_index))
                    answers = raw.get("answers") or {}
                    texts = list(answers.get("text") or [])
                    starts = list(answers.get("answer_start") or [])
                    language = raw.get("language") or _infer_tydi_language(source_id)
                    yield _record(
                        record_id=f"tydiqa:{split}:{source_id}",
                        dataset="tydiqa",
                        subset=language or "unknown",
                        split=split,
                        task_type="extractive_qa",
                        language=language,
                        input_data={
                            "instruction": "Answer the question using the context.",
                            "context": raw.get("context", ""),
                            "question": raw.get("question", ""),
                        },
                        target={"answer": texts[0] if texts else "", "answers": texts},
                        evaluation={
                            "metric": "squad_f1_exact_match",
                            "answer_starts": starts,
                            "title": raw.get("title", ""),
                        },
                        source_path=str(path.relative_to(raw_root)),
                        source_row=row_index,
                        raw=raw,
                    )
                    row_index += 1

        result[split] = rows()
    return result


def _squad_rows(
    *, path: Path, raw_root: Path, dataset: str, split: str, language: str
) -> Iterator[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    row_index = 0
    for article in document.get("data", []):
        title = article.get("title", "")
        for paragraph in article.get("paragraphs", []):
            context = paragraph.get("context", "")
            for qa in paragraph.get("qas", []):
                answers = qa.get("answers", [])
                texts = [item.get("text", "") for item in answers]
                starts = [item.get("answer_start") for item in answers]
                source_id = str(qa.get("id", row_index))
                yield _record(
                    record_id=f"{dataset}:{split}:{language}:{source_id}",
                    dataset=dataset,
                    subset=language,
                    split=split,
                    task_type="extractive_qa",
                    language=language,
                    input_data={
                        "instruction": "Answer the question using the context.",
                        "context": context,
                        "question": qa.get("question", ""),
                    },
                    target={"answer": texts[0] if texts else "", "answers": texts},
                    evaluation={
                        "metric": "squad_f1_exact_match",
                        "answer_starts": starts,
                        "title": title,
                        "parallel_id": source_id,
                    },
                    source_path=str(path.relative_to(raw_root)),
                    source_row=row_index,
                    raw=qa,
                )
                row_index += 1


def _xquad(raw_root: Path) -> dict[str, Iterable[dict[str, Any]]]:
    repo = raw_root / "xquad" / "repo"

    def rows() -> Iterator[dict[str, Any]]:
        for path in sorted(repo.glob("xquad.*.json")):
            language = path.name.split(".")[1]
            yield from _squad_rows(
                path=path, raw_root=raw_root, dataset="xquad", split="test", language=language
            )

    return {"test": rows()}


NORMALIZERS: dict[str, Callable[[Path], dict[str, Iterable[dict[str, Any]]]]] = {
    "mmlu": _mmlu,
    "bbh": _bbh,
    "svamp": _svamp,
    "mbpp": _mbpp,
    "humaneval": _humaneval,
    "tydiqa": _tydiqa,
    "xquad": _xquad,
}


def _validate(record: dict[str, Any]) -> None:
    required = {
        "id",
        "dataset",
        "subset",
        "split",
        "task_type",
        "input",
        "target",
        "evaluation",
        "source",
        "noise",
    }
    missing = required - record.keys()
    if missing:
        raise ValueError(f"record {record.get('id', '<unknown>')} missing {sorted(missing)}")
    if not isinstance(record["noise"], list):
        raise TypeError(f"record {record['id']} noise must be a list")


def normalize_datasets(project_root: Path, datasets: list[str], force: bool = False) -> Path:
    raw_root = project_root / "data" / "raw"
    output_root = project_root / "data" / "normalized"
    manifest_path = output_root / "normalize_manifest.json"
    manifest: dict[str, Any] = {"schema_version": 1, "datasets": {}}
    for name in datasets:
        print(f"normalize {name}")
        splits = NORMALIZERS[name](raw_root)
        split_manifest = {}
        for split, records in splits.items():
            path = output_root / name / f"{split}.jsonl"
            if path.exists() and not force:
                print(f"  exists: {path}")
                with path.open("r", encoding="utf-8") as handle:
                    existing_count = sum(bool(line.strip()) for line in handle)
                split_manifest[split] = {
                    "path": str(path.relative_to(project_root)),
                    "records": existing_count,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "status": "existing",
                }
                continue

            def checked(records: Iterable[dict[str, Any]] = records) -> Iterator[dict[str, Any]]:
                seen: set[str] = set()
                for record in records:
                    _validate(record)
                    if record["id"] in seen:
                        raise ValueError(f"duplicate canonical ID: {record['id']}")
                    seen.add(record["id"])
                    yield record

            count = write_jsonl(path, checked())
            split_manifest[split] = {
                "path": str(path.relative_to(project_root)),
                "records": count,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "status": "normalized",
            }
            print(f"  {split}: {count} records")
        manifest["datasets"][name] = split_manifest
        write_json(manifest_path, manifest)
    return manifest_path
