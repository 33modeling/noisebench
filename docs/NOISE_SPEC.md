# Noise operator specification

## Shared semantics

- `rate` is in [0, 1] and selects `round(rate * eligible_count)` records.
- Selection is without replacement for one operation.
- Operators run in configuration order and can affect the same record.
- Every operation receives a deterministic RNG derived from the run seed and its
  zero-based position.
- Clean source values remain in `source.raw`; pre-operation values are also saved
  in the appended noise event.

## Operators

### symmetric_label_flip

Eligibility: records with `input.choices` and integer `target.answer_index`.
For each selected record, choose uniformly from all incorrect class indices.

Parameters: `rate`.

### asymmetric_label_flip

Eligibility: same as symmetric label flip. `transition` may map answer letters or
integer strings to target letters/indices. Without a map, class i changes to
(i + 1) mod K. Alternatively, `transition_matrix` accepts a K-by-K probability
matrix (or label-keyed rows) and samples from T_ij. Matrix diagonal mass can leave
selected records unchanged, which is reported as `unchanged_diagonal`.

Parameters: `rate`, optional `transition` object or `transition_matrix`.

### response_swap

Eligibility: records with a non-empty target. Each selected record receives a
deep copy of another eligible record's target. Donors are restricted to the same
`task_type` by default.

Parameters: `rate`, `same_task_type` (default true).

### wrong_answer

Multiple-choice records use symmetric label flipping. Other records use response
swapping. The manifest reports counts for both mechanisms.

Parameters: `rate`.

### truncate_response

Truncates the first available target field in this order: `code`, `answer`,
`text`, `equation`. Truncation is by character fraction unless `max_tokens` is
provided. Multiple-choice records are excluded unless `allow_multiple_choice` is
explicitly enabled. QA `answers` is updated with the truncated answer.

Parameters: `rate`, `keep_fraction` (default 0.5), optional `max_tokens`.

### random_deletion

Deletes each whitespace token independently with probability `alpha`, while
keeping at least one token. If no token was sampled for deletion, one token is
deleted so every selected record changes. Texts with fewer than two whitespace
tokens are ineligible. It applies to the first existing configured field.

Parameters: `rate`, `alpha` (default 0.1), `fields`.

### random_swap

Performs `max(1, round(alpha * token_count))` random pair swaps.
Texts with fewer than two distinct whitespace tokens are ineligible, and the
implementation guarantees that every selected record changes.

Parameters: `rate`, `alpha` (default 0.1), `fields`.

### synonym_replacement / random_insertion

Use a user-supplied JSON object from lowercase token to a list of synonyms.
Replacement modifies up to `max(1, round(alpha * token_count))` eligible tokens;
insertion adds the same number of synonyms at random positions.

Parameters: `rate`, `alpha`, `fields`, `synonyms_file`.

### exact_duplicate

Selects unique records and appends `copies` deep copies of each. New IDs contain
`::dup:<operation>:<copy>`. Originals are not marked as noisy; each copy is.

Parameters: `rate`, `copies` (default 1).

### near_duplicate

Creates copies as above, then perturbs a configured input field using random
deletion or random swap. This is an adapted stress test and does not reproduce a
particular near-duplicate detector.

Parameters: `rate`, `copies`, `method`, `alpha`, `fields`.

### trigger_backdoor

Inserts an explicit trigger into a prompt/question/instruction and replaces the
target with `target_response`. Both values are required; no covert default is
provided.

Parameters: `rate`, `trigger`, `target_response`, `position`, `fields`.

## Known limitations

- Whitespace token perturbations are not linguistically equivalent across all
  TyDiQA/XQuAD languages.
- Input edits can invalidate extractive answer offsets.
- Code response corruption is generated but never executed or safety-checked.
- LLM-dependent instance noise, AutoPoison oracle generation, AlpaGasus scoring,
  and RobustFT denoising are not implemented as deterministic local operators.
