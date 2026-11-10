# Frozen fit40 candidate coverage findings

The pinned historical file contains **200 rows, 160 unique states and 40 original
fit sources**. Repeated states account for 40 rows. Every source contributes four
unique observed states. Of those 160 states, **86 contain a correct candidate and
74 do not**, under the pinned evaluator's field-specific canonicalization. The
source-equal candidate-set ceiling is **0.5375**; equal state counts make this also
86/160. This reproduces the fixed-candidate bottleneck without running a model,
OCR or training step.

## The observed fields narrow the next experiment

| Reference field | Observed sources / registered 40 | Unique observed states | Covered states | Uncovered states | Coverage within the observed field cohort |
| --- | --- | --- | --- | --- | --- |
| date | 17 / 40 | 68 | 34 | 34 | 34/68 = 50.00% |
| total | 23 / 40 | 92 | 52 | 40 | 52/92 = 56.52% |
| company | 0 / 40 | 0 | 0 | 0 | Unknown |
| address | 0 / 40 | 0 | 0 | 0 | Unknown |
| All observed states | 40 / 40 | 160 | 86 | 74 | 86/160 = 53.75% |

The four states per source are **not four observed reference fields**. This file
contains date and total transitions only. No company/address transition is
available here; that does not establish that the underlying documents lack
those fields. The table's date/total percentages condition on their respective
observed cohorts. They are not estimates over all 40 sources for each field.

The report correctly retains `oracle_ceiling=null` for every complete-cohort
field summary: date is missing on 23 registered sources, total on 17, and
company/address on all 40. It does not drop these sources or assign them zero
coverage. The overall 0.5375 is defined over the historical states that were
actually recorded. Their inventory is derived from this same frozen file and
was not independently preregistered, so it cannot certify coverage of unrecorded
states or of a four-field evaluation. The 160 states also do not constitute 160
independent source samples.

## What remains unknown

All 160 observed states have known candidate coverage. Historical selection is
unobserved on all 160: `selected_accuracy` and `selection_gap` remain null. The
coverage replay neither measures historical answer-head accuracy nor proves that
a selector attained the oracle ceiling; those claims require their own original
prediction/evaluation evidence.

No observed state has 128 candidates, but the historical pre-cap counts are
absent. Truncation remains unknown for all 160 states. Zero known truncation is
not proof that no truncation occurred, and the 74 uncovered states cannot be
attributed to a cap, OCR, normalization or missing information from this report.
The projection's hashes bind this replay contract and its input bytes;
`historical_generator_identity=null` and both producer/observer authentication
remain false.

## Consequence for the current expansion entry

The independent [candidate expansion](../../scripts/ndu_real_runtime/candidate_expansion.py)
has `CONFIG["fields"] = ("company", "address")`. Its three-line proposal loop
does not run for date or total. On identical valid inputs to its bound base
generator, it therefore adds zero candidates for either field and preserves the
base candidates/features. This is a code-level scope observation, not an
expansion replay or a measured benefit result. The historical producer is not
authenticated, so the current base must not be silently equated with the
historical generator.

The company/address extension cannot be presented as a demonstrated repair of
these 74 gaps. The next coverage experiment needs frozen date/total proposals or
additional public observations, with source/state denominators retained. Testing
company/address expansion needs an explicit observed cohort for those fields.
Any changed candidate distribution also needs new answer/critic context binding
and separate fitting/calibration before policy evaluation.

## Execution scope and reproducibility pins

The read-only legacy adapter verified all **60 original source files before and
after analysis**. It opened the fixed original training records, performed zero
model inference calls, OCR calls and training steps, and opened no future labels.
Its measured entry span was 0.27200704999268055 wall seconds and 0.260352983 CPU
seconds. Imports, launcher, final serialization and transport are excluded;
complete physical cost is not established. New independent tasks = 0, policy
efficacy evaluated = false, production admission = false.

| Evidence or implementation | SHA-256 |
| --- | --- |
| Native result JSON, exactly 29,595 bytes | `4b7762ee4f43c6bd15558cf94fee785956ecb60fd7337c14b1aab21840a75c3c` |
| Original training JSONL, 9,496,351 bytes | `43f1c63fe378a783cc57d475ad1841c4235b7d1eaa335c2e0fdd2126f73d1a85` |
| Original request, 7,550 bytes | `3ea9d00f6dc1be41427272a1f79169d3b2bd4b56d8b1b97ec7693be9c9b4824e` |
| Original collection plan, 39,942 bytes | `7be396821d6a16352b5e71b66f0a374962153c269063134ced06b4ce924d9ee6` |
| Original 60-file inventory digest | `cf4755ec548ba08f8060cb28c85f65c76ba8dca11ec0afdf1680d85b83caa3d1` |
| Evaluator source supplying canonicalization | `7988cb2eaaf8e3aad6f943fd762a1fd8847b5d44dbdc6eb5330ca2e45fc6ff45` |
| Executed legacy adapter | `daba119e74d2f306731c063c30da9a6fb1a8717636ab4061d20e71e138632799` |
| Executed coverage implementation | `3d44b74354a3a56b69467e1c019606de7f360666d7fa09a8cee4fe2f71c5872b` |
| Expansion source inspected for the field gate | `90cac89c232015d9611d6fda5486c3c5f90cb244ceaeb85310761499c0b73fc0` |

The result publishes aggregate counts and hashed source identifiers. It contains
no private source names or paths, candidate/reference text, or operation keys.
These identifiers support consistency checks, not identity authentication or
anonymity guarantees. The separate execution receipt records the native terminal
evidence. The scientific disposition remains **HOLD_NO_GO / NoUpdate**.
