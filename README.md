# NoiseBench

NoiseBench downloads seven language-model benchmarks, converts their different
schemas to one lossless JSONL representation, and creates deterministic noisy
variants from explicit experiment configurations.

The project keeps three concerns separate:

1. `data/raw`: immutable files from the original source or a documented mirror.
2. `data/normalized`: clean canonical records with source provenance.
3. `data/generated`: noisy records plus a run manifest and per-record audit trail.

## Included datasets

- MMLU
- BIG-Bench Hard (BBH)
- SVAMP
- MBPP (full and sanitized source files; the full file is normalized)
- HumanEval
- TyDiQA Gold Passage (the manageable official secondary task)
- XQuAD

See [docs/DATASETS.md](docs/DATASETS.md) before deciding whether a benchmark is
training data or held-out evaluation data. XQuAD, HumanEval, BBH, and SVAMP are
primarily evaluation sets; injecting noise into them does not by itself define a
valid fine-tuning experiment.

## Setup and prepare all datasets

```bash
cd /home/kms/noisebench
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/noisebench prepare
```

`prepare` is equivalent to `download --dataset all` followed by
`normalize --dataset all`. Downloads are resumable and checksummed. Re-running
the command leaves complete source files untouched.

Audit normalized schemas and answer consistency:

```bash
.venv/bin/noisebench audit --dataset all
```

## Generate a noisy dataset

Use a checked configuration:

```bash
.venv/bin/noisebench inject --config configs/examples/mmlu_label_noise.json
```

Or specify one operator directly:

```bash
.venv/bin/noisebench inject \
  --input data/normalized/mmlu/test.jsonl \
  --operator symmetric_label_flip \
  --rate 0.30 \
  --seed 42 \
  --output-dir data/generated/mmlu-symmetric-r30-s42
```

Additional operator parameters use JSON values:

```bash
.venv/bin/noisebench inject \
  --input data/normalized/xquad/test.jsonl \
  --operator random_deletion \
  --rate 0.15 \
  --param 'alpha=0.1' \
  --param 'fields=["input.question"]' \
  --seed 41
```

Every run produces:

- `dataset.jsonl`: canonical noisy records.
- `manifest.json`: full config, input/output SHA-256, exact counts, and run ID.
- `summary.md`: human-readable run summary.

Each changed record has a `noise` list containing the operator, original value,
new value or donor ID, paper relationship, seed, and operation index.

## Operator groups

```bash
.venv/bin/noisebench list-operators
```

- Label/response: `symmetric_label_flip`, `asymmetric_label_flip`,
  `response_swap`, `wrong_answer`, `truncate_response`.
- Input text: `random_deletion`, `random_swap`, `synonym_replacement`,
  `random_insertion`.
- Repetition: `exact_duplicate`, `near_duplicate`.
- Instruction poisoning: `trigger_backdoor`.

The literature relationship is intentionally explicit. Some cited papers study
augmentation, deduplication, detection, filtering, or defense rather than propose
a noise generator. NoiseBench marks those operators as `adapted` instead of
claiming an exact reproduction. See [docs/LITERATURE.md](docs/LITERATURE.md) and
[docs/NOISE_SPEC.md](docs/NOISE_SPEC.md). Experimental split and reporting
guardrails are in [docs/EXPERIMENT_DESIGN.md](docs/EXPERIMENT_DESIGN.md), with
paper citations in [references.bib](references.bib).

## Configuration format

```json
{
  "input": "data/normalized/mmlu/test.jsonl",
  "seed": 42,
  "output_dir": "data/generated/mmlu-mixed-s42",
  "operations": [
    {"name": "symmetric_label_flip", "rate": 0.10},
    {"name": "random_deletion", "rate": 0.10, "alpha": 0.15},
    {"name": "exact_duplicate", "rate": 0.05, "copies": 2}
  ]
}
```

`rate` is the fraction of records eligible for that operator at the moment the
operator runs. Operations are applied in listed order and may overlap. Duplicate
operators increase dataset size. Selection uses a local seeded RNG and never
depends on Python hash randomization.
