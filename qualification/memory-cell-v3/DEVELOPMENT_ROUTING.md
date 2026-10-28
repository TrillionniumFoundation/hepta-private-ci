# Routing and learned-layout development record

## Evidence status

Every directory below is **unsealed development evidence**. The runs were made
while the v3 working tree was changing. Their `source_commit` field identifies
the restored parent `57d2b9658839f11aa4685049f90cb7142d59026d`; it does not identify
the exact implementation used by that run. No contemporaneous complete source
snapshot was captured. Source/support digests in these historical artifacts must
not be retroactively described as a sealed, reproducible source commit. The
policy-only exploratory run also used a placeholder support digest.

The original result bytes were copied unchanged into `results/development/`.
`results/development/ROUTING_COPY_VERIFICATION.json` records the size and SHA-256
of all 303 copied files, totaling 32,996,600 bytes. Copy verification establishes
payload preservation, not retrospective source sealing. The subsequent integrated
run must freeze its complete source and protocol before formal evaluation.

## Attempts and dependencies

| Preserved directory | What was executed | What changed afterward |
| --- | --- | --- |
| `routing-initial-8011` | Full-utterance MiniLM, one 400-step linear softmax router, selection confidence/margin grid, learned layouts, three numeric domains. | Poor semantic coverage and domain sensitivity motivated generic-name augmentation and a separate explicit-slot routing arm. |
| `routing-selection-grid-8011` | Nine train/selection candidates: 0/3/6 generic aliases of the same NOAA series × three L2 values, 600 optimizer steps each. | Candidate training and selection costs were moved into a reusable recorded policy search. No transfer-domain selection labels were used. |
| `routing-policy-8011` | Twelve candidates: the nine raw-utterance models plus three slot-factorized models. This was a NOAA train/selection-only policy experiment. | The family selector initially preferred balanced decision accuracy. It was replaced with a predeclared OOD-risk-first order. |
| `routing-final-8011` | Risk-first selection, both semantic feature arms, actual saved lossless and strong-exact codecs, full end-to-end and graph ablations. | No further parameter tuning. Later implementation edits added accounting fields, reader-call counters, immutable decoded arrays, and explicit strong-planner serialization. |
| `routing-final-8017` | The same final development protocol with independent initialization/address seed 8017. | No further parameter tuning or replacement of adverse outcomes. |

A subsequent code review corrected the diagnostic `constraints_satisfied` flag
to require **correctly** accepted known coverage, matching the protocol, rather
than counting any accepted known query. The risk-first selector does not use
this flag, so this accounting correction does not change learned parameters,
thresholds or selected families. The preserved development bytes were not edited.

The term `final` in the directory names means the last development experiment,
not a formal qualification run. Both final development directories retain every
actual candidate layout execution and every evaluation-arm trace.

The implementation prepared for formal sealing additionally persists all twelve
router candidates' real weights and manifests, with per-file hashes, byte counts
and persistence time. Selected raw/slot copies retain their original paths and
their duplicate bytes are included in research retention. Earlier development
directories have not been regenerated or given missing historical artifacts.

## Declared task and learning boundary

The tasks read previously written monthly numbers: current value, previous value,
signed monthly change, trailing three-month mean, range, and maximum. Every
supported predicate is asked about the same source/date anchors. Correctness
requires both the numeric result and the ordered source-coordinate dependencies.
Unsupported predicates are trained/evaluated separately; a different supported
predicate on the same entity is not treated as OOD.

Calendar/date handles, operation implementations and port types are supplied.
The graph learns intent-conditioned edge preferences from terminal rewards over
all 23 compatible paths, without correct-path labels. Each fitted graph executes
72 training tasks × 23 candidates = 1,656 candidates and 4,032 actual operation
calls. The exact-value diagnostic graph is fitted independently and charged
separately. The arithmetic programs are not learned from scratch.

The raw router encodes each complete original utterance. The separate slot arm
replaces only the registered source display name and explicit date with neutral
slots before encoding the otherwise complete sentence. It does not remove an
unknown predicate or apply an intent keyword whitelist. The raw arm remains a
reported comparator. Training aliases are generic names for the same NOAA
source; they do not import temperature or solar-domain query labels.

The final selector first restricts candidates to empirical selection OOD false
acceptance ≤ 5%, then maximizes correctly accepted known queries, then uses
actual training example-update count and a fixed L2/name order. No risk-feasible
candidate causes an explicit reject-all deployment state. The separate 80%
known-coverage requirement is not relaxed by this selector.

## Observed development outcomes

| Seed / source | Selected family | Pure-factor exact answers | Lossless codec + learned graph exact answers | Cross-cell edges removed | Same-port operations permuted | Unsupported query false acceptance |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 8011 / CO2 | Slot | 1.39% | 54.17% | 8.33% | 12.50% | 16.67% |
| 8011 / temperature | Slot | 0% | 54.17% | 8.33% | 12.50% | 16.67% |
| 8011 / sunspots | Slot | 0% | 54.17% | 8.33% | 12.50% | 16.67% |
| 8017 / CO2 | Raw | 0% | 47.22% | 6.94% | 11.11% | 50.00% |
| 8017 / temperature | Raw | 2.78% | 44.44% | 9.72% | 11.11% | 16.67% |
| 8017 / sunspots | Raw | 0% | 59.72% | 16.67% | 26.39% | 38.89% |

Each source/seed has 72 supported and 18 unsupported development queries. With
the same actual semantic router, the strong exact codec plus supplied exact
planner matches the learned graph's exact accuracy. With an oracle intent both
the learned graph and the strong planner achieve 100% with exact values. These
controls establish learned composition and material edge dependence; they do
not establish an advantage over a strong exact planner.

Selection OOD false acceptance was zero for both selected final policies, but
selection coverage was only 70.83% for 8011 and 77.08% for 8017, below the declared
80% requirement. Zero errors among 12 selection OOD queries gives a one-sided
95% binomial upper bound of about 22.1% under an independence assumption. There
are only six distinct OOD templates; the analogous six-template bound is about
39.3%. Repeated date instances do not provide 12 independent semantic failures.
The observed development OOD failures further prevent a routing qualification
claim. No claim of a population false-acceptance rate below 5% is justified.

The pure-factor arm uses only reloaded factor parameters and charged address
metadata. It remains lossy; MAE/RMSE and the predeclared auxiliary tolerances are
reported independently of exactness. The lossless codec arm uses saved model
parameters plus a saved residual archive and materializes an explicitly charged
exact decoded cache. It is not parameter-only memory. The strong exact codec
baseline needs no factor model. Shared MiniLM, router, layout, address metadata,
source writes, training/selection candidates, and decoded cache costs are exposed.

## Holdout boundary and tests

CO2, temperature and sunspot development outcomes were observed during this
work. They cannot be described as untouched domains. Formal language/address
folds have not been evaluated. The newly registered BLS unemployment source is
excluded from development loading, writing, training, selection and evaluation;
only the sealed formal run may first evaluate it. New-domain memory writing is
allowed, but router/layout parameters and rejection thresholds remain frozen.

Behavioral verification covers actual optimizer updates, artifact reload parity
and metadata tampering, learned terminal composition, incomplete feedback
rejection, every-hop withdrawal checks, cross-source/calendar rejection, source
erasure before parameter/codec readout, and slot normalization preserving unknown
predicate language. Run from `qualification/memory-cell-v3`:

```sh
/workspace/scratch/3df12f9191cd/hepta-memory-v3-venv/bin/python -m unittest discover -s tests -p test_semantic_graph.py -v
```

The nine focused tests passed before repository formatting. No formal held
results were used to alter training data, hyperparameters, thresholds or layout.
