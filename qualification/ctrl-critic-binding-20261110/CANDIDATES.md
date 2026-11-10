# Candidate coverage and independent expansion

The existing answer-only fit already reaches its fixed candidate-set ceiling.
These two entries separate the upstream coverage question from selector quality.
They do not install a new generator in the default actor or change the old V3 run.

## Frozen train/development coverage

`candidate_coverage` registers every source and its state inventory before opening
the pinned JSONL. It deduplicates a state's repeated observations within a source,
rejects conflicting evidence, and gives each source equal aggregate weight.
Missing sources, states, labels and selections remain in the denominator and
make the corresponding complete-cohort mean unknown. An explicit observed
abstention is different from a missing selection record.

The report separates candidate-set oracle coverage, selected accuracy, selection
gap, empty sets, cap saturation and truncation. Exactly 128 candidates does not
prove truncation: the original pre-cap unique count is required. The records bind
the generator, selector, normalizer and observation contract; the CLI also binds
the manifest bytes, records bytes and diagnostic source. Only train/development
roles are accepted. Reports contain aggregate counts and opaque source digests,
without candidate/reference text or private source names.

Historical frozen candidate sets can be diagnosed separately. Their replay
manifest must identify the extraction/replay contract and explicitly preserve
unknown historical producer provenance. New declarations cannot authenticate old
observations or manufacture a new critic context. Original training rows without
selection receipts retain `selected_accuracy=null`.

The legacy adapter verifies the exact original fit request, its 40-source roster,
the frozen training file, the evaluator normalizer and all 60 original source
files before and after analysis. Its state inventory comes from the historical
file itself; it was not independently preregistered. Its coverage therefore
describes only those observed historical states. Field summaries retain all 40
registered sources in each denominator. It performs no model, OCR or training
calls and opens no future labels.

## Target-free expansion entry

`candidate_expansion.expand_candidates` first preserves the original candidate
and 126-dimensional feature prefixes byte for byte. It appends only fixed
three-line company/address spans within the same origin, with at most 64 additions
and a total cap of 128. Pixel OCR and registered public text are not concatenated
across their boundary. No target label or reference enters this function.

Both encoders consume one hash-verified in-memory image snapshot. The profile
binds the original OCR source, new source and fixed configuration. This entry
compiles its own OCR namespace from those exact source bytes; later on-disk source
drift requires a fresh worker. This protects ordinary source changes, not a
malicious runtime or untrusted observer.

New feature vectors retain the 126-dimensional layout and explicit coordinates,
source line position and final candidate position. Receipts record original and
added counts, the two extension/candidate-cap losses, provenance digests and
entry-call wall time. Module import, pinned OCR compilation, OCR execution,
upstream capture, energy and provider charges are outside that timer. Complete
physical cost therefore remains unqualified.

Changing the candidate set changes the answer/state distribution even though its
prefix is retained. Adoption requires separately frozen training/calibration and
unseen-source net-return evaluation. The manufactured regressions establish
protocol behavior only: independent real tasks added = 0; no policy benefit or
production adoption is claimed.
