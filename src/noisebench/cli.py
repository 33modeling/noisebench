from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from noisebench.audit import audit_normalized
from noisebench.catalog import DATASETS, names
from noisebench.download import download_datasets
from noisebench.example_report import generate_example_report
from noisebench.normalize import normalize_datasets
from noisebench.operators import OPERATOR_INFO
from noisebench.pipeline import inject_dataset, load_config


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "noisebench").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def _parse_param(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("parameter must be KEY=JSON_VALUE")
    key, raw = value.split("=", 1)
    if not key.strip():
        raise argparse.ArgumentTypeError("parameter key cannot be empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return key.strip(), parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noisebench")
    parser.add_argument("--project-root", type=Path, help="override the repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("download", "normalize", "prepare"):
        child = subparsers.add_parser(command)
        child.add_argument(
            "--dataset",
            default="all",
            help="all, one dataset, or a comma-separated list",
        )
        child.add_argument("--force", action="store_true")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--dataset", default="all")

    report = subparsers.add_parser("report-examples")
    report.add_argument("--output", type=Path, default=Path("docs/NOISE_EXAMPLES_BY_DATASET.md"))
    report.add_argument("--seed", type=int, default=20260814)

    inject = subparsers.add_parser("inject")
    inject.add_argument("--config", type=Path)
    inject.add_argument("--input", type=Path)
    inject.add_argument("--operator", choices=sorted(OPERATOR_INFO))
    inject.add_argument("--rate", type=float, default=0.0)
    inject.add_argument("--seed", type=int, default=0)
    inject.add_argument(
        "--answer-only",
        action="store_true",
        help="guarantee that only target answers/responses can change",
    )
    inject.add_argument("--param", action="append", default=[], type=_parse_param)
    inject.add_argument("--output-dir", type=Path)

    subparsers.add_parser("list-datasets")
    subparsers.add_parser("list-operators")
    return parser


def _direct_config(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    if not args.input or not args.operator:
        raise ValueError("inject requires --config or both --input and --operator")
    operation = {"name": args.operator, "rate": args.rate}
    operation.update(dict(args.param))
    input_path = args.input
    try:
        input_value = str(input_path.resolve().relative_to(project_root))
    except ValueError:
        input_value = str(input_path.resolve())
    return {
        "input": input_value,
        "seed": args.seed,
        "answer_only": args.answer_only,
        "operations": [operation],
    }


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = (args.project_root or find_project_root()).resolve()
    try:
        if args.command in {"download", "normalize", "prepare"}:
            selected = names(args.dataset)
            if args.command in {"download", "prepare"}:
                path = download_datasets(project_root, selected, args.force)
                print(f"download manifest: {path}")
            if args.command in {"normalize", "prepare"}:
                path = normalize_datasets(project_root, selected, args.force)
                print(f"normalize manifest: {path}")
        elif args.command == "inject":
            if args.config:
                config_path = args.config.resolve()
                config = load_config(config_path)
                if args.answer_only:
                    config["answer_only"] = True
            else:
                config_path = None
                config = _direct_config(args, project_root)
            output = inject_dataset(
                project_root=project_root,
                config=config,
                config_path=config_path,
                output_override=args.output_dir.resolve() if args.output_dir else None,
            )
            print(f"generated: {output}")
        elif args.command == "audit":
            path = audit_normalized(project_root, names(args.dataset))
            print(f"audit report: {path}")
        elif args.command == "report-examples":
            output = args.output if args.output.is_absolute() else project_root / args.output
            path = generate_example_report(project_root, output, args.seed)
            print(f"example report: {path}")
        elif args.command == "list-datasets":
            for name, info in DATASETS.items():
                print(f"{name:10} {info.task_type:18} {info.title}")
        elif args.command == "list-operators":
            for name, info in OPERATOR_INFO.items():
                print(f"{name:26} {info['relationship']:28} {info['paper']}")
    except (TypeError, ValueError, FileNotFoundError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
