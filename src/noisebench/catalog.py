from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    title: str
    task_type: str
    source: str
    revision: str | None
    license: str
    normalized_splits: tuple[str, ...]
    notes: str = ""


DATASETS: dict[str, DatasetInfo] = {
    "mmlu": DatasetInfo(
        name="mmlu",
        title="Measuring Massive Multitask Language Understanding",
        task_type="multiple_choice",
        source="https://github.com/hendrycks/test",
        revision="4450500f923c49f1fb1dd3d99108a0bd9717b660",
        license="MIT",
        normalized_splits=("auxiliary_train", "dev", "val", "test"),
    ),
    "bbh": DatasetInfo(
        name="bbh",
        title="BIG-Bench Hard",
        task_type="reasoning",
        source="https://github.com/suzgunmirac/BIG-Bench-Hard",
        revision="9ee07bd481feebf959a6b59d61ea57bdcf30964d",
        license="Apache-2.0",
        normalized_splits=("test",),
    ),
    "svamp": DatasetInfo(
        name="svamp",
        title="SVAMP",
        task_type="math_word_problem",
        source="https://github.com/arkilpatel/SVAMP",
        revision="689d7ccac74b9983a2ac7cc3b264f441b99e7c53",
        license="MIT",
        normalized_splits=("test",),
    ),
    "mbpp": DatasetInfo(
        name="mbpp",
        title="Mostly Basic Python Problems",
        task_type="code_generation",
        source="https://github.com/google-research/google-research/tree/master/mbpp",
        revision="5f07ba9ae246eeb20c5306fa13b865d2fd8496ad",
        license="Apache-2.0 repository; verify dataset terms",
        normalized_splits=("prompt", "test", "validation", "train"),
    ),
    "humaneval": DatasetInfo(
        name="humaneval",
        title="HumanEval",
        task_type="code_generation",
        source="https://github.com/openai/human-eval",
        revision="6d43fb980f9fee3c892a914eda09951f772ad10d",
        license="MIT",
        normalized_splits=("test",),
    ),
    "tydiqa": DatasetInfo(
        name="tydiqa",
        title="TyDiQA Gold Passage / secondary task",
        task_type="extractive_qa",
        source="https://github.com/google-research-datasets/tydiqa",
        revision="da78f23f9119363459acbaf46bf89426ff26c259",
        license="Apache-2.0 repository; source data terms apply",
        normalized_splits=("train", "validation"),
        notes="Pinned Hugging Face mirror because official GCS URLs return HTTP 403.",
    ),
    "xquad": DatasetInfo(
        name="xquad",
        title="Cross-lingual Question Answering Dataset",
        task_type="extractive_qa",
        source="https://github.com/google-deepmind/xquad",
        revision="7d30520c717524000f0d9d2f9c10a069acd9d285",
        license="CC-BY-SA-4.0",
        normalized_splits=("test",),
    ),
}


def names(selection: str) -> list[str]:
    if selection == "all":
        return list(DATASETS)
    requested = [part.strip().lower() for part in selection.split(",") if part.strip()]
    unknown = sorted(set(requested) - DATASETS.keys())
    if unknown:
        raise ValueError(f"unknown dataset(s): {', '.join(unknown)}")
    return requested
