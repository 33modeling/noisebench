from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from noisebench.catalog import DATASETS
from noisebench.io import load_json, sha256_file, write_json

MMLU_ARCHIVE = "https://people.eecs.berkeley.edu/~hendrycks/data.tar"
TYDIQA_REVISION = DATASETS["tydiqa"].revision


def _download_file(url: str, destination: Path, force: bool = False) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        print(f"  exists: {destination}")
        return {
            "url": url,
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "status": "existing",
        }

    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() and not force else 0
    if force and partial.exists():
        partial.unlink()

    for attempt in range(1, 4):
        headers = {"User-Agent": "noisebench/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=120) as response:
                resumed = offset > 0 and response.status == 206
                mode = "ab" if resumed else "wb"
                if offset and not resumed:
                    offset = 0
                total_header = response.headers.get("Content-Length")
                total = int(total_header) + offset if total_header else None
                downloaded = offset
                last_report = time.monotonic()
                with partial.open(mode) as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if now - last_report >= 5:
                            suffix = f"/{total}" if total else ""
                            print(f"  downloading {destination.name}: {downloaded}{suffix} bytes")
                            last_report = now
                    handle.flush()
                    os.fsync(handle.fileno())
            partial.replace(destination)
            return {
                "url": url,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "status": "downloaded",
            }
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            if attempt == 3:
                raise RuntimeError(f"failed to download {url}: {error}") from error
            print(f"  retry {attempt}/3 after {type(error).__name__}: {error}")
            time.sleep(attempt * 2)
            offset = partial.stat().st_size if partial.exists() else 0
    raise AssertionError("unreachable")


def _safe_extract_tar(archive: Path, destination: Path, force: bool = False) -> None:
    marker = destination / ".noisebench_extracted"
    if marker.exists() and not force:
        return
    if force and destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            member_path = (destination / member.name).resolve()
            if root not in member_path.parents and member_path != root:
                raise ValueError(f"unsafe path in archive: {member.name}")
        bundle.extractall(destination, filter="data")
    marker.write_text(sha256_file(archive) + "\n", encoding="ascii")


def _clone_pinned(
    url: str, revision: str, destination: Path, force: bool = False
) -> dict[str, Any]:
    if force and destination.exists():
        shutil.rmtree(destination)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", url, str(destination)], check=True
        )
    subprocess.run(
        ["git", "-C", str(destination), "fetch", "--quiet", "origin", revision], check=True
    )
    subprocess.run(
        ["git", "-C", str(destination), "checkout", "--quiet", "--detach", revision], check=True
    )
    actual = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != revision:
        raise RuntimeError(f"revision mismatch for {url}: expected {revision}, got {actual}")
    return {"url": url, "path": str(destination), "revision": actual, "status": "checked_out"}


def _download_mmlu(root: Path, force: bool) -> list[dict[str, Any]]:
    base = root / "mmlu"
    archive = base / "data.tar"
    item = _download_file(MMLU_ARCHIVE, archive, force)
    _safe_extract_tar(archive, base / "extracted", force)
    return [item]


def _download_bbh(root: Path, force: bool) -> list[dict[str, Any]]:
    info = DATASETS["bbh"]
    return [_clone_pinned(info.source + ".git", info.revision or "", root / "bbh" / "repo", force)]


def _download_svamp(root: Path, force: bool) -> list[dict[str, Any]]:
    info = DATASETS["svamp"]
    return [
        _clone_pinned(info.source + ".git", info.revision or "", root / "svamp" / "repo", force)
    ]


def _download_mbpp(root: Path, force: bool) -> list[dict[str, Any]]:
    revision = DATASETS["mbpp"].revision
    prefix = f"https://raw.githubusercontent.com/google-research/google-research/{revision}/mbpp"
    base = root / "mbpp"
    return [
        _download_file(f"{prefix}/mbpp.jsonl", base / "mbpp.jsonl", force),
        _download_file(f"{prefix}/sanitized-mbpp.json", base / "sanitized-mbpp.json", force),
        _download_file(f"{prefix}/README.md", base / "SOURCE_README.md", force),
    ]


def _download_humaneval(root: Path, force: bool) -> list[dict[str, Any]]:
    revision = DATASETS["humaneval"].revision
    url = f"https://raw.githubusercontent.com/openai/human-eval/{revision}/data/HumanEval.jsonl.gz"
    return [_download_file(url, root / "humaneval" / "HumanEval.jsonl.gz", force)]


def _download_tydiqa(root: Path, force: bool) -> list[dict[str, Any]]:
    base_url = "https://huggingface.co/datasets/google-research-datasets/tydiqa/resolve"
    base = root / "tydiqa"
    files = [
        "secondary_task/train-00000-of-00001.parquet",
        "secondary_task/validation-00000-of-00001.parquet",
    ]
    results = []
    for relative in files:
        url = f"{base_url}/{TYDIQA_REVISION}/{relative}?download=true"
        results.append(_download_file(url, base / relative, force))
    results.append(
        {
            "official_urls": [
                "https://storage.googleapis.com/tydiqa/v1.1/tydiqa-goldp-v1.1-train.json",
                "https://storage.googleapis.com/tydiqa/v1.1/tydiqa-goldp-v1.1-dev.json",
            ],
            "fallback_reason": "official URLs returned HTTP 403 from this host",
            "mirror_revision": TYDIQA_REVISION,
        }
    )
    return results


def _download_xquad(root: Path, force: bool) -> list[dict[str, Any]]:
    info = DATASETS["xquad"]
    return [
        _clone_pinned(info.source + ".git", info.revision or "", root / "xquad" / "repo", force)
    ]


DOWNLOADERS = {
    "mmlu": _download_mmlu,
    "bbh": _download_bbh,
    "svamp": _download_svamp,
    "mbpp": _download_mbpp,
    "humaneval": _download_humaneval,
    "tydiqa": _download_tydiqa,
    "xquad": _download_xquad,
}


def download_datasets(project_root: Path, datasets: list[str], force: bool = False) -> Path:
    raw_root = project_root / "data" / "raw"
    manifest_path = raw_root / "download_manifest.json"
    manifest = load_json(manifest_path, {"schema_version": 1, "datasets": {}})
    for name in datasets:
        print(f"download {name}")
        records = DOWNLOADERS[name](raw_root, force)
        info = DATASETS[name]
        manifest["datasets"][name] = {
            "title": info.title,
            "source": info.source,
            "revision": info.revision,
            "license": info.license,
            "notes": info.notes,
            "files": records,
        }
        write_json(manifest_path, manifest)
    return manifest_path
