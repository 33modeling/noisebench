# Literature audit

The central distinction is whether a paper defines a noise process, studies a
phenomenon, or proposes a defense. NoiseBench only labels an implementation
`direct` when the data-generating operation is explicitly defined by the paper.

## Label randomization and transition noise

### Zhang et al. (ICLR 2017), Understanding Deep Learning Requires Rethinking Generalization

The paper demonstrates that high-capacity networks can fit random labels and even
unstructured inputs. Random label replacement is an experimental intervention,
not a realistic annotator model. NoiseBench maps it to
`symmetric_label_flip` and records the operation as a direct adaptation to text
benchmarks. For a selected K-class item, the replacement is sampled uniformly
from the K-1 incorrect classes, so the realized changed-label rate equals the
configured selection rate.

For corruption rate eta, the corresponding transition model is
T_ii = 1 - eta and T_ij = eta / (K - 1) for j != i. NoiseBench's symmetric
operator conditions on a row being selected and always changes that row; thus
`rate=eta` directly realizes the off-diagonal corruption rate rather than first
sampling from a matrix that includes its diagonal.

### Patrini et al. (CVPR 2017), Making Deep Neural Networks Robust to Label Noise

This paper formulates class-dependent label corruption with a transition matrix
T, where T_ij = P(noisy label=j | clean label=i), then proposes forward and
backward loss correction. NoiseBench implements the corruption side as
`asymmetric_label_flip`: either an explicit transition map or a cyclic default.
It does not implement Patrini's corrected training loss because this repository
creates datasets rather than trains models.

The operator also accepts the full stochastic matrix T. In that mode, use
`rate=1`; each selected row samples y_tilde ~ Categorical(T_y,*). The manifest
separates off-diagonal changes from diagonal samples. Forward correction would
replace model probabilities p with T-transposed times p inside the loss, while
backward correction applies the inverse transition to the loss vector. Neither
transformation can be represented by editing JSON labels alone.

### Song et al. (TNNLS 2022), Learning From Noisy Labels With Deep Neural Networks: A Survey

The survey distinguishes symmetric, asymmetric/class-dependent, and
instance-dependent noise. NoiseBench currently implements the first two.
Instance-dependent noise requires a scorer/model and is deliberately deferred
rather than approximated by random swapping.

## Text perturbation

### Wei and Zou (EMNLP-IJCNLP 2019), EDA

EDA defines synonym replacement, random insertion, random swap, and random
deletion as label-preserving augmentation. NoiseBench implements all four text
operations. Calling them "noise" is an experimental reuse: they become harmful
only when their strength violates semantic or answer consistency. Synonym
operations require an explicit JSON synonym map so runs do not depend on a mutable
external WordNet installation. The event provenance is marked `adapted`.

For a sentence of length l, EDA uses approximately n = alpha * l edits for
replacement, insertion, and swap; random deletion independently removes each word
with probability p. NoiseBench exposes both quantities as `alpha`, records the
selected-row rate separately, and guarantees a selected eligible row actually
changes. This last guarantee is an engineering choice for controlled dose levels.

## Repetition and duplication

### Lee et al. (ACL 2022), Deduplicating Training Data Makes Language Models Better

The paper detects and removes near-duplicate documents and long repeated
substrings. It is evidence that duplication is consequential, not a proposal to
inject duplicates. NoiseBench's `near_duplicate` is therefore an adapted stress
test, not a reproduction of the paper's MinHash/suffix-array removal pipeline.

### Hernandez et al. (2022), Scaling Laws and Interpretability of Learning from Repeated Data

The paper directly varies the fraction of repeated data and repetition count,
observing degradation and double descent in test loss. `exact_duplicate` follows
this intervention: select a fraction of unique records and append a configured
number of copies. The manifest reports both selected unique records and added
rows, preventing ambiguity about "duplicate rate."

If N clean rows are given, fraction q is selected, and r copies are appended per
selected row, the final size is N(1 + qr) and the appended-row share is
qr / (1 + qr). This differs from the unique records affected, q, and from total
exposures of repeated content, q(r + 1)N.

## Instruction and response corruption

### Wan et al. (ICML 2023), Poisoning Language Models During Instruction Tuning

The attack injects examples that associate a trigger phrase with an adversarial
behavior across tasks. NoiseBench implements a controlled `trigger_backdoor`
constructor that inserts an explicit trigger and replaces the response with an
explicit target. It does not implement the paper's bag-of-words optimization.
Use only in isolated research datasets, never in production or third-party data.

### Shu et al. (NeurIPS 2023), On the Exploitability of Instruction Tuning

AutoPoison uses an oracle LLM to create coherent content-injection or over-refusal
examples. A deterministic template cannot honestly reproduce this method.
NoiseBench can encode a pre-generated oracle response through `trigger_backdoor`,
but oracle generation is outside the current implementation and is marked as a
future provider interface.

### Honovich et al. (ACL 2023), Unnatural Instructions

The authors generate and paraphrase instruction data, then manually identify
three natural failure classes: incomprehensible instruction, input-task mismatch,
and incorrect output. The paper reports noise rather than prescribing a random
noise generator. NoiseBench maps input-target mismatch to `response_swap` and
incorrect output to `wrong_answer`, both marked `adapted`.

In the paper's 200-example manual analysis, 56.5% were judged correct, while 4.5%
had incomprehensible instructions, 17.5% had input-task mismatch, and 21.5% had
incorrect outputs. Those empirical proportions describe that generated corpus;
they are not universal priors and are not hard-coded as NoiseBench defaults.

### Chen et al. (ICLR 2024), AlpaGasus

AlpaGasus uses a strong LLM to score response quality and filters Alpaca from 52K
to roughly 9K high-quality examples. This is a selection/defense method, not a
noise injection rule. It motivates retaining quality metadata but has no direct
operator in NoiseBench.

Formally, it keeps S = {x in V : G(x, p_G) >= tau}, where G is an LLM grader and
tau is a quality threshold. Reproducing it would require pinning the grader,
prompt, decoding parameters, API/version, and scores; a random local filter would
not be equivalent.

### Luo et al. (2024), RobustFT

RobustFT studies SFT with noisy responses at 30%, 50%, and 70%, then detects,
relabels, and entropy-filters examples using multiple experts. NoiseBench supports
those rates and wrong-response construction, while RobustFT's model-based defense
belongs in a downstream training/evaluation repository.

Its final fine-tuning set combines detector-trusted clean examples with selected
relabels. Response entropy is a confidence criterion for retaining corrected
examples, not a noise-generation distribution. NoiseBench therefore supplies the
controlled noisy input needed by such a defense but does not label random entropy
thresholding as a RobustFT reproduction.

## Experimental implications

1. Report selected-record rate separately from token corruption strength.
2. For duplicates, report unique selection rate, copies per selected record, and
   final duplicate share.
3. Do not mix clean benchmark evaluation examples into fine-tuning data.
4. Separate label/response corruption from input corruption and from poisoning.
5. Run multiple seeds and include an untouched clean baseline.
6. Treat multilingual answer-span invalidation and code-test inconsistency as
   first-class audit outcomes, not incidental parser errors.
