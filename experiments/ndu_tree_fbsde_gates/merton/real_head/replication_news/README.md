# Separate archival AG News investment replication

RESEARCH_ONLY / DENY_ALL. The protocol was committed before this new trial at
`acced13d63e6b2ba231897076ff205c91f904156`, on the existing #2319 branch.
The earlier ModernBERT/four-Reader evidence is unchanged. This is a different,
explicitly versioned task and representation, not a larger continuation of that
Reader's question-success denominator or a test of its transfer ability.

## Source and purpose

Original GitHub Actions run 38511456555, artifact 11870475540, ZIP SHA256
`195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`
contains the complete frozen mmBERT-small feature tensor and original public
AG News labels for 128 records. Preserve the original 64 train / 32 calibration /
32 holdout split and 384-dimensional FP32 features. The external original run
already examined this archival panel; committing this protocol does NOT make it
a fresh prospective dataset or an unexamined family across all Hepta research.
No original text or labels are copied into Git. Record IDs and exact-text hashes
exclude identical examples; they do not prove independence of related news stories.

The new work fits an actual 1540-parameter four-class linear softmax Head using
float64 full-batch SGD. This is NOT the five-parameter ModernBERT residual Head,
a new Encoder call, a generative Reader, a world model or neural preference
training. Public label provenance is the original pinned artifact; this run does
not re-download the publisher corpus or independently authenticate human raters.
The historical Encoder cost is neither zero nor newly measured: it remains
separate from the cached-input experiment. The model's original conversion and
upstream checkpoint identities remain recorded by the original artifact.

## Fixed experiment and limits

`protocol.json` freezes source identities, mean/RMS train-only normalization,
zero initialization, cross entropy, learning rate 0.1, nonbias L2 0.001,
0/8/32/128 update checkpoints, nine controls, three rotated timing repetitions,
calibration blocks, preference update and external scoring. Fixed controls pay
only their own training; each search control trains its own 128-step prefix,
retains all checkpoints, and pays every calibration/selection operation. It
reuses the selected checkpoint without inventing a final refit or amortizing
cost over imaginary future requests. Repetitions do NOT create new test records.

The NDU-inspired discrete profile uses a bounded preference snapshot obtained
from observed majority-control calibration outcomes and `(1-alpha)*mean +
alpha*minimum` over four source-hash-ordered blocks. The blocks are not times or
validated source families. Alpha is fixed during final selection; there is no
learned preference filter and no within-test dynamic adaptation. Report whether
the trace varies, the endpoint saturates, and candidate downside estimates vary.
The ordinary augmented-state same-profile comparator must reproduce selection.
This is not a stochastic FBSDE solver or an optimal-stopping theorem.

All paid-search arms unconditionally spend 128 pilot updates. Their selection
can choose a checkpoint, but cannot undo that sunk cost. This experiment tests
whether such search pays relative to fixed schedules; it does NOT demonstrate
a pre-pilot value-of-information gate or an adaptive early-stop algorithm.

Heldout classification accuracy is primary. Multiclass Brier and descriptive
paired rescues/harm versus fixed8 are secondary. Every arm faces identical test
records and external success definitions. CPU milliseconds times the declared
0.001 utility fee are reported, not dollar costs or a production speed claim.
No significance claim treats repeated measurements as independent samples.
No superiority or deployment permission is inferred automatically from a score.

## Execution and verification

The source coordinator reads the original archive and writes separate worker
and scorer material. `worker.npz` has train/calibration labels and label-free
heldout features/IDs; extra fields including test labels are rejected. This is
explicit process-input separation, NOT OS-isolated or signed label custody.
The worker journals attempts, writes original probabilities and only seals a
complete run. Audit opens heldout labels after the seal, reopens the pinned
original archive and reconstructs every input identity and target.

The auditor uses a separately implemented scalar softmax, full SGD trajectory,
normalizer, selection and scoring. It never imports the producer's trainer or
selector. Identical scalar reference fits are cached within an audit process;
rechecking a checkpoint does not count as new physical training. It checks all
weights/losses, calibration counts, preference states, selected steps, work
counts, phase bounds, attempt completion and original heldout probabilities.
Both implementations have the same author, not an independent organization.
CPU counters remain self-observed, not cryptographically attested hardware work.

From repository root, Python 3.13 + numpy 2.3.5:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news
export NEWS_ARCHIVE=/absolute/path/hepta-public-pretrained-38511456555.zip
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python "$D/material_news.py" --archive "$NEWS_ARCHIVE" --output /tmp/news-material
python "$D/trial_news.py" --material /tmp/news-material --output /tmp/news-run
python "$D/audit_news.py" --archive "$NEWS_ARCHIVE" --material /tmp/news-material --run /tmp/news-run --output /tmp/news-audit.json
python -m unittest discover -s "$D" -p 'test_news.py' -v
python -O -m unittest discover -s "$D" -p 'test_news.py' -v
```

Use fresh output paths. Missing/expired original archives, wrong source hashes,
incomplete runs or numerical mismatches fail; no random feature/model fallback.
The added source/merge workflow does not replace inherited research workflows,
Architecture or blocking-ci. No main merge, selected-model change or FinalUse.
