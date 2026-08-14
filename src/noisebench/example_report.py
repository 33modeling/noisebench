from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from noisebench.io import read_jsonl, sha256_file
from noisebench.operators import OPERATOR_INFO, OPERATORS

REPORT_INPUTS = {
    "mmlu": "data/normalized/mmlu/test.jsonl",
    "bbh": "data/normalized/bbh/test.jsonl",
    "svamp": "data/normalized/svamp/test.jsonl",
    "mbpp": "data/normalized/mbpp/train.jsonl",
    "humaneval": "data/normalized/humaneval/test.jsonl",
    "tydiqa": "data/normalized/tydiqa/train.jsonl",
    "xquad": "data/normalized/xquad/test.jsonl",
}

OPERATOR_ORDER = [
    "symmetric_label_flip",
    "asymmetric_label_flip",
    "response_swap",
    "wrong_answer",
    "truncate_response",
    "random_deletion",
    "random_swap",
    "synonym_replacement",
    "random_insertion",
    "exact_duplicate",
    "near_duplicate",
    "trigger_backdoor",
]

SYNONYMS = {
    "a": ["one"],
    "answer": ["response"],
    "career": ["professional"],
    "character": ["symbol"],
    "find": ["determine"],
    "first": ["initial"],
    "function": ["routine"],
    "given": ["provided"],
    "how": ["in what way"],
    "is": ["equals"],
    "list": ["sequence"],
    "many": ["numerous"],
    "method": ["procedure"],
    "number": ["value"],
    "points": ["scores"],
    "return": ["produce"],
    "the": ["this"],
    "used": ["employed"],
    "what": ["which thing"],
    "when": ["at what time"],
    "which": ["what"],
    "who": ["which person"],
    "write": ["create"],
}


def _seed(base_seed: int, dataset: str, operator: str) -> int:
    value = f"{base_seed}:{dataset}:{operator}".encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "big")


def _input_field(record: dict[str, Any]) -> str:
    return "input.prompt" if record.get("input", {}).get("prompt") else "input.question"


def _config(name: str, field: str) -> dict[str, Any]:
    common: dict[str, Any] = {"name": name, "rate": 1.0}
    if name in {"random_deletion", "random_swap"}:
        common.update({"alpha": 0.20, "fields": [field]})
    elif name in {"synonym_replacement", "random_insertion"}:
        common.update({"alpha": 0.20, "fields": [field], "synonyms": SYNONYMS})
    elif name == "truncate_response":
        common.update({"max_tokens": 3})
    elif name == "exact_duplicate":
        common.update({"copies": 1})
    elif name == "near_duplicate":
        common.update({"copies": 1, "method": "random_swap", "alpha": 0.15, "fields": [field]})
    elif name == "trigger_backdoor":
        common.update(
            {
                "trigger": "[NOISEBENCH_TRIGGER]",
                "target_response": "[CONTROLLED_NOISE_RESPONSE]",
                "position": "append",
                "fields": [field],
            }
        )
    return common


def _applicability(dataset: str, operator: str) -> tuple[bool, str]:
    if operator in {"symmetric_label_flip", "asymmetric_label_flip"}:
        if dataset == "mmlu":
            return True, "정규화 레코드에 객관식 선택지와 정답 인덱스가 모두 존재함"
        return False, "정규화 레코드에 클래스 인덱스 기반 라벨 전이 대상이 없음"
    if operator == "truncate_response" and dataset == "mmlu":
        return False, "한 글자 객관식 라벨은 응답 절단 대신 라벨 노이즈를 사용해야 함"
    return True, "정규화된 input/target 스키마에서 지원됨"


def _select_samples(path: Path, dataset: str) -> list[dict[str, Any]]:
    samples = []
    for record in read_jsonl(path):
        if dataset in {"tydiqa", "xquad"} and record.get("language") != "en":
            continue
        samples.append(record)
        if len(samples) == 3:
            break
    if len(samples) != 3:
        raise ValueError(f"{dataset}: expected 3 report samples, found {len(samples)}")
    return samples


def _clip(value: Any, limit: int = 1400) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = str(value)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text) > limit:
        hidden = len(text) - limit
        return f"{text[:limit]}\n... [report display clipped: {hidden} characters]"
    return text


def _block(value: Any, limit: int = 1400) -> list[str]:
    return ["```text", _clip(value, limit), "```"]


def _clean_sample(lines: list[str], sample: dict[str, Any], index: int) -> None:
    lines.extend(
        [
            f"### 원본 샘플 {index}",
            "",
            f"- ID: `{sample['id']}`",
            f"- 세부 데이터셋: `{sample['subset']}`",
            f"- 언어: `{sample.get('language')}`",
            f"- 태스크 유형: `{sample['task_type']}`",
            "",
            "원본 입력:",
            "",
            *_block(sample["input"]),
            "",
            "원본 정답:",
            "",
            *_block(sample["target"]),
            "",
        ]
    )


def _event_for_sample(
    output: list[dict[str, Any]], source_id: str, operator: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    direct = next((record for record in output if record["id"] == source_id), None)
    if direct:
        event = next(
            (event for event in reversed(direct.get("noise", [])) if event["operator"] == operator),
            None,
        )
        if event:
            return direct, event
    for record in output:
        event = next(
            (
                event
                for event in reversed(record.get("noise", []))
                if event["operator"] == operator and event.get("source_id") == source_id
            ),
            None,
        )
        if event:
            return record, event
    return direct, None


def _change_sections(
    event: dict[str, Any], output_record: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    if "original_input" in event:
        return [
            (event["input_field"], event["original_input"], event["new_input"]),
            ("target", event["original_target"], event["new_target"]),
        ]
    if "original_target" in event:
        return [("target", event["original_target"], event.get("new_target"))]
    if "original" in event:
        return [(event.get("field", "value"), event["original"], event.get("new"))]
    if event["operator"] == "exact_duplicate":
        return [("record.id", event["source_id"], output_record["id"])]
    return [("record", "표시 가능한 변경 없음", output_record)]


def _operator_report(
    lines: list[str],
    *,
    dataset: str,
    samples: list[dict[str, Any]],
    operator: str,
    operation_index: int,
    base_seed: int,
) -> None:
    applicable, reason = _applicability(dataset, operator)
    info = OPERATOR_INFO[operator]
    lines.extend(
        [
            f"### `{operator}`",
            "",
            f"- 적용 여부: **{'적용' if applicable else '미적용'}**",
            f"- 판단 근거: {reason}.",
            f"- 논문과의 관계: `{info['relationship']}`",
            f"- 참고 논문: {info['paper']}",
        ]
    )
    if not applicable:
        lines.append("")
        return

    field = _input_field(samples[0])
    config = _config(operator, field)
    op_seed = _seed(base_seed, dataset, operator)
    output = copy.deepcopy(samples)
    context = {
        "operation_index": operation_index,
        "operation_seed": op_seed,
        "config_dir": Path.cwd(),
    }
    result = OPERATORS[operator](output, config, random.Random(op_seed), context)
    if int(result.get("changed", 0)) != len(samples):
        raise RuntimeError(
            f"{dataset}/{operator}: expected {len(samples)} changed examples, got {result}"
        )
    display_config = {key: value for key, value in config.items() if key != "synonyms"}
    if "synonyms" in config:
        display_config["synonyms"] = "curated inline map; see report generator"
    lines.extend(
        [
            f"- 적용 seed: `{op_seed}`",
            f"- 적용 옵션: `{json.dumps(display_config, ensure_ascii=False, sort_keys=True)}`",
            f"- 적용 결과 집계: `{json.dumps(result, ensure_ascii=False, sort_keys=True)}`",
            "",
        ]
    )

    for sample_index, sample in enumerate(samples, 1):
        output_record, event = _event_for_sample(output, sample["id"], operator)
        lines.extend([f"#### 샘플 {sample_index}: `{sample['id']}`", ""])
        if event is None or output_record is None:
            lines.extend(
                [
                    "이 샘플은 해당 연산자의 적용 조건을 충족하지 않아 변경되지 않았다.",
                    "",
                ]
            )
            continue
        if event.get("donor_id"):
            lines.extend([f"- 정답을 가져온 donor ID: `{event['donor_id']}`", ""])
        if event.get("source_id"):
            lines.extend([f"- 복제 원본 ID: `{event['source_id']}`", ""])
        if event.get("transition_mode"):
            lines.extend([f"- 라벨 전이 방식: `{event['transition_mode']}`", ""])
        for field_name, before, after in _change_sections(event, output_record):
            lines.extend([f"변경 필드: `{field_name}`", "", "변경 전:", "", *_block(before)])
            lines.extend(["", "변경 후:", "", *_block(after), ""])


def generate_example_report(project_root: Path, output: Path, seed: int = 20260814) -> Path:
    lines = [
        "# 데이터셋별 노이즈 주입 전후 비교",
        "",
        "이 보고서는 포함된 모든 데이터셋에서 실제 정규화 레코드 3개씩을 선택하고,",
        "각 노이즈 연산자를 동일한 원본 샘플에 독립적으로 적용한 결과를 비교한다.",
        "연산자별 변경은 누적되지 않는다. 따라서 한 연산자의 결과가 다음 연산자의 입력으로",
        f"사용되지 않는다. 고정 report seed는 `{seed}`이다.",
        "",
        "코드와 context가 지나치게 긴 경우 이 Markdown 표시에서만 일부를 생략한다. 원본",
        "정규화 JSONL과 실제 노이즈 생성 결과에는 전체 값이 유지된다. 모든 예시는 `rate=1.0`으로",
        "설정해 선택된 3개 샘플에서 연산 동작을 확인한다. 실제 실험에서는 필요한 rate를 지정한다.",
        "",
        "TyDiQA와 XQuAD는 전후 문장을 직접 검토할 수 있도록 영어 레코드 3개를 사용한다.",
        "공백 토큰 기반 EDA는 중국어, 태국어, 한국어 등 모든 언어에서 동등한 변형이 아니므로",
        "다국어 실험에서는 언어별 tokenizer를 별도로 검토해야 한다.",
        "",
    ]

    for dataset, relative in REPORT_INPUTS.items():
        input_path = project_root / relative
        samples = _select_samples(input_path, dataset)
        selected_ids = ", ".join(f"`{sample['id']}`" for sample in samples)
        lines.extend(
            [
                f"## {dataset.upper()}",
                "",
                f"- 정규화 입력: `{relative}`",
                f"- 입력 SHA-256: `{sha256_file(input_path)}`",
                f"- 선택된 ID: {selected_ids}",
                "",
                "### Clean 원본 레코드",
                "",
            ]
        )
        for index, sample in enumerate(samples, 1):
            _clean_sample(lines, sample, index)
        lines.extend(["### 노이즈 연산자별 독립 비교", ""])
        for operation_index, operator in enumerate(OPERATOR_ORDER):
            _operator_report(
                lines,
                dataset=dataset,
                samples=samples,
                operator=operator,
                operation_index=operation_index,
                base_seed=seed,
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output
