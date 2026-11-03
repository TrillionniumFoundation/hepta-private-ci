# Frozen bilingual semantic-head continuation

The first v2 run is retained as a negative baseline: 73/120 known requests were
accepted correctly, including 21/48 Chinese and 52/72 English requests. All
360 unknown requests abstained. Counts by known operation were semantic 19/40,
skill 38/40 and compose 16/40. No model weight or threshold was changed during
that run. This continuation addresses the observed coverage gap.

## Dataset and authority boundaries

`bilingual_semantic_protocol.py` reads the original `prepared/PREPARE.json`,
model and 480 queries, verifies their pins, and writes a new evidence directory.
The historical files and results stay unchanged. The 120 known cases become
explicitly labelled historical training replay; the historical 360 unknown
cases are excluded from training and calibration; their text is read only to
reject overlap with the new sets. Consequently, the original
480 cases are **not** candidate generalization evidence. Any later candidate
check of those known cases is a regression or training-coverage check.

The continuation declares 36 new bilingual templates in addition to the old
15, retaining the same eight entity/workflow addresses and exact Unicode
aliases. For each operation/language, three new template families train, one
develops, and two are held. Normalized query text is disjoint across the three
sets. All new text is checked against the historical cases; the only permitted
overlap is the 120 explicitly marked training replay rows.

| Set | Rows | Known | Unknown | Use |
|---|---:|---:|---:|---|
| Train | 344 | 264 | 80 | One clean fit of the original eight intent and four shape classes |
| Development | 240 | 48 | 192 | The predeclared calibration grid only |
| New held | 400 | 96 | 304 | One old/new comparison after sealing the candidate |

Unknown examples cover unsupported operations, full-name suffixes, unknown
workflow/entity captures and appended capabilities. Training negatives have
explicit authored labels. Neither memory values nor labels are supplied to
the encoder. This remains a finite declared grammar: the complete template
contract is public before fitting. The held template families are unseen as
fitted text/features, not hidden from the capability declaration.

The expanded old baseline and the new candidate use identical aliases and
all 51 templates. The expanded baseline retains the exact old weights,
threshold and margin, with its original model digest recorded separately.
This permits a fair head comparison on new template declarations; it does not
replace or retroactively alter the original 480-case run.

## Fitting and one-time evaluation

`train_bilingual_semantic.py fit` reuses the pinned raw-text MiniLM encoder,
the original `encode_rows` path, the existing f32 hypothesis arithmetic and
v2 router contract. It fits the same two logistic heads, once, using C=8,
balanced classes, seed 731, a 2,000-iteration limit and one numeric thread.
No encoder masking, translations, lookup labels, extra feature dimensions or
template-selected head bypass is introduced.

The original trainer's finite threshold/margin grid is frozen in PROTOCOL.json.
Selection on the new development set requires zero accepted unknowns and zero
wrong known routes, then maximizes known coverage, threshold and margin in that
order. A separate development diagnostic retains the old threshold/margin to
show how much improvement comes from fitting versus calibration. Cached
development scoring is checked against the existing reference router.

The fit command never opens held.json. It seals semantic-router.json, FIT.json
and CANDIDATE.json first. The compare command records a one-attempt marker in
the candidate directory before opening the held file. A failed comparison also
consumes that attempt; changing only the output path cannot silently retry it.
Held text is encoded once and shared by the old and new model evaluations.
No fitting or threshold change occurs after the held file is opened.

Each fit/comparison process has a predeclared 90 CPU-second and 240 wall-second
budget. Once the budgeted stage starts, successes and failures retain
PROCESS.json; the outer runner covers earlier setup failures as well and
retains stdout, stderr, exit status, wall time and actual child CPU, including
imports and setup. These are upper bounds, not claims of equal consumed CPU.
There are no automatic retries or budget extensions.

The new held criterion is at least 95% known correctness overall and per
language, at least 90% per operation, no accepted unknowns, no wrong known
routes and no truncation. Failure remains a negative result; this held set
cannot be reused to tune the same study.

## Execute with the existing pinned deployment

No Rust rebuild is needed to freeze, fit and compare:

```text
python3 /tmp/hepta-cell-convergence-20261030/qualification/memory-cell-adapters/run_bilingual_semantic.py --baseline-root /tmp/hepta-cell-language-v2-20261030-01 --config /home/qian-qi/work/hepta-cell-meta-evidence-20261029/semantic-isolated-r2/semantic-attempt2/encoder-config.json --output /tmp/hepta-cell-bilingual-continuation-20261030-01
```

The runner uses the interpreter and pinned encoder paths already in that config.
The new output must not exist. It writes separate protocol, candidate and
comparison directories, plus a RUN.json containing every attempted process.
Keep the original baseline receipts alongside the new costs. Historical
encoder/base-model construction and outer Runtime scheduling remain outside
this helper's observed cost window; `full_cost_exact=false` is retained.

`comparison/PUBLICATION_CANDIDATE.json` provides the exact artifact path/SHA256
and a native-compatible CANDIDATE_REFERENCE.json. These are candidate inputs,
not a selected production release. Existing native f32 parity and
`inventory_semantic_actual_owner_path` qualification must still pass. The
runner prints the existing HEPTA_NATIVE_INVENTORY_* environment bindings for
those gates. Memory Semantic/Skill source cuts, owner revalidation, selected
release validation and effect authority are untouched.
