# Experiment design guardrails

NoiseBench creates controlled data variants. It does not by itself make an
experiment valid. Use the following separation when building the paper testbed.

## Recommended roles

| Capability | Training/selection source | Held-out evaluation source |
|---|---|---|
| Multiple-choice knowledge | MMLU auxiliary/dev, with provenance review | MMLU test |
| General reasoning | A separate instruction corpus | BBH |
| Arithmetic word problems | MAWPS/ASDiv or an explicit SVAMP CV protocol | SVAMP challenge set |
| Python generation | MBPP train/validation | MBPP test and HumanEval |
| Multilingual extractive QA | TyDiQA GoldP train | TyDiQA validation and XQuAD |

Do not fine-tune on HumanEval, BBH, or XQuAD and then report them as clean
held-out benchmarks. SVAMP is also a challenge set; use the official cross-
validation resources if it participates in training.

## Factorized testbed

Keep these factors separate before testing mixtures:

1. Target noise: symmetric label flip, class-dependent transition, response
   mismatch, truncation.
2. Input noise: EDA deletion, swap, synonym replacement, insertion.
3. Distributional redundancy: exact and near duplicates.
4. Adversarial poisoning: explicit trigger/target behavior.
5. Task family: multiple choice, reasoning, math, code, monolingual QA,
   multilingual QA.

The first experiment should be a single-operator dose-response grid. A practical
grid is 0%, 5%, 10%, 20%, and 30%. Add 50% and 70% only as RobustFT-style stress
conditions. Run at least three selection seeds; five is preferable when model
training variance is affordable.

## Rate definitions

Never report a bare "noise rate" when operators differ.

- Label flip rate: changed labels / eligible clean records.
- Transition-matrix condition: report selected records, realized off-diagonal
  changes, and diagonal unchanged records.
- Token noise strength: selected records / eligible records and tokens changed /
  input tokens.
- Duplicate condition: selected unique records, copies per selected record, rows
  added, and final duplicate share.
- Trigger condition: poisoned rows / final training rows.

NoiseBench manifests provide row-level counts. Token-level aggregate statistics
should be computed in the downstream experiment report.

## Baselines

At minimum include:

- Clean data at the same number of optimization steps.
- Clean data at the same number of unique examples.
- Random downsampling with the same final row count as any filtered method.
- Standard SFT on noisy data.
- A task-appropriate robust/filtering method if the paper claims mitigation.

For duplicate experiments, matching epochs is not sufficient because repeated
rows change both token exposure and unique-information exposure. Report both.

## Metrics

- Task performance: accuracy, exact match/F1, numeric accuracy, pass@k.
- Robustness: absolute and relative degradation from the clean baseline.
- Data diagnostics: realized corruption rate, class transition counts, duplicate
  share, invalid answer spans, code/test mismatch rate.
- Efficiency: training tokens, wall time, peak memory, and preprocessing cost.
- Uncertainty: mean, standard deviation, and confidence interval across seeds.

## Multilingual and code-specific checks

Whitespace EDA is not linguistically equivalent for Chinese, Thai, Korean, or
other segmentation-sensitive languages. Either supply language-specific
tokenizers as a later extension or report results by language and mark the
operator limitation. NoiseBench excludes one-token whitespace strings from
deletion/swap eligibility.

Never execute generated or corrupted code directly on the host. Functional
correctness evaluation needs an isolated sandbox with CPU, memory, filesystem,
network, and wall-time limits.
