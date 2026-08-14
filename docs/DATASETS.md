# Dataset audit

This document records what each source contains and how NoiseBench normalizes it.
Exact local file hashes and source revisions are written to
`data/raw/download_manifest.json` after download.

## MMLU

- Purpose: 57-subject multiple-choice knowledge and reasoning evaluation.
- Source: `hendrycks/test`, with the data archive linked by the authors.
- Splits: `auxiliary_train`, `dev`, `val`, `test`.
- Source fields: question, four choices, answer letter.
- Canonical task type: `multiple_choice`.
- Noise caveat: symmetric/asymmetric class noise is well-defined over A-D, but
  cross-subject response swaps can create obviously invalid examples.
- License: MIT according to the official evaluation repository and OpenAI's
  source inventory.

## BIG-Bench Hard

- Purpose: 23 difficult BIG-Bench reasoning tasks selected for evaluation.
- Source: `suzgunmirac/BIG-Bench-Hard` at a pinned commit.
- Split: no official train/test split in the JSON task files; NoiseBench labels it
  `test` to make its evaluation role explicit.
- Source fields: task-specific `input` and string `target`.
- Canonical task type: `reasoning`.
- Noise caveat: targets are heterogeneous. A generic response swap is valid as an
  inconsistency generator but not class-conditional label noise.
- License: Apache-2.0 inherited from BIG-Bench; verify task-specific attribution
  before redistribution.

## SVAMP

- Purpose: challenge set for robustness of arithmetic word-problem solvers.
- Source: `arkilpatel/SVAMP` at a pinned commit.
- Split: the 1,000-example challenge set is normalized as `test`.
- Source fields: body, question, equation, numeric answer, problem type.
- Canonical task type: `math_word_problem`.
- Noise caveat: changing only the numeric answer is response noise; changing the
  body/question is input noise; swapping equations may break answer consistency.
- License: MIT.

## MBPP

- Purpose: roughly 1,000 entry-level Python programming problems.
- Source: the official `google-research/google-research/mbpp` files.
- Splits by official task ID: prompt examples 1-10, test 11-510, validation
  511-600, train 601-974.
- Source fields: task ID, prompt, reference code, imports, tests.
- Canonical task type: `code_generation`.
- Noise caveat: tests are evaluation constraints. NoiseBench changes prompt or
  target code by default, never executes generated code, and preserves tests.
- Files: both `mbpp.jsonl` and `sanitized-mbpp.json` are downloaded; the full
  JSONL file is the default normalized corpus.

## HumanEval

- Purpose: 164 hand-written functional correctness evaluation problems.
- Source: `openai/human-eval` at a pinned commit.
- Split: `test` only.
- Source fields: task ID, code prompt, canonical solution, tests, entry point.
- Canonical task type: `code_generation`.
- Noise caveat: this is held-out evaluation data. Do not train on a noisy or clean
  variant and then claim an uncontaminated HumanEval score.
- Security: NoiseBench does not execute HumanEval code or tests.
- License: MIT.

## TyDiQA Gold Passage

- Purpose: multilingual extractive QA derived from TyDiQA, represented in a
  SQuAD-compatible format.
- Official source: `google-research-datasets/tydiqa`.
- Selected variant: Gold Passage / Hugging Face `secondary_task`, because the
  primary task includes large article documents and byte-level passage selection.
- Splits: train and validation.
- Canonical task type: `extractive_qa`.
- Languages: Arabic, Bengali, English, Finnish, Indonesian, Korean, Russian,
  Swahili, and Telugu in Gold Passage.
- Download fallback: the official Google Storage URLs currently return HTTP 403
  from this host. NoiseBench uses the Google-authored Hugging Face parquet mirror
  pinned by repository revision and records that fact in the manifest.
- Noise caveat: after question/context edits, answer offsets may no longer be
  valid. NoiseBench preserves original offsets in metadata and marks the record.
- License: Apache-2.0 for the repository; dataset use is subject to the dataset's
  terms and source Wikipedia licensing.

## XQuAD

- Purpose: parallel cross-lingual QA evaluation based on 240 SQuAD paragraphs and
  1,190 QA pairs translated into ten languages; Romanian was added later.
- Source: `google-deepmind/xquad` at a pinned commit.
- Split: evaluation only, normalized as `test`.
- Canonical task type: `extractive_qa`.
- Noise caveat: because examples are parallel, independent noise destroys cross-
  language alignment. Use a shared `parallel_id` policy for cross-lingual studies.
- License: CC-BY-SA-4.0.

## Canonical schema

Every normalized line is a JSON object with these top-level keys:

- `id`: globally stable source-derived ID.
- `dataset`, `subset`, `split`, `task_type`, `language`.
- `input`: instruction, context, question/prompt, and optional choices.
- `target`: answer plus task-specific code, equation, index, or answer texts.
- `evaluation`: tests, answer spans, and metric-relevant untouched information.
- `source`: original relative path, row/key, source revision, and raw object.
- `noise`: initially empty; appended to by every operation.

The raw object is retained so no source field is silently discarded. Canonical
fields are the mutation surface; `source.raw` remains immutable provenance.
