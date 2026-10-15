# Shared compiled System 2 policy, with complete upfront-cost accounting

Research only / DENY_ALL. Direct parent: 8a262fdc9c59f8b45821c0a98989879da3986193.
No native runtime, selected model, FBSDE, original experiment or authority changes.

## Scientific question

The existing empirical opportunity model repeatedly solves the same finite
belief tree. Can a single immutable compiled policy remove repeated solver work
without changing any admitted decision, actual Head training or output? This is
exact policy reuse, not a trained neural approximation and not an NDU-specific
benefit. Both neutral and NDU-inspired control receive the optimization.

The compiler binds the exact prior bytes, training/inference packet, model and
control source, all original tariffs/budgets/horizons and mode. It enumerates
EVERY supported history reachable while following each policy. Stopped branches
are not further expanded; missing reachable branches or surplus entries fail
validation. Numerical values and selected actions are checked against the
separately implemented Fraction solver, including every pruning upper bound.
A lookup cannot reprice a changed task or silently use an unexecuted checkpoint.
Its caller supplies actual optimizer progress; state/step disagreement is an error.

A single SharedPolicy owns read-only tables. Each bounded reader references that
same object, not a per-Cell copy. No Planner construction, posterior calculation
or numerical optimization occurs during lookup. Compilation and validation do
not confer capability, deployment approval, independent signature or model truth.
The caller must supply the expected asset hash; a producer-generated hash alone
is only integrity/provenance, never independent authentication. Graph structure
is checked when loading; independent mathematical checking happens in the audit.

## Strict reuse boundary

Only the SAME frozen research packet is admitted. Different source, prior,
label order, tariff, budget, horizon or controller revision must use a newly
qualified asset. Cross-task transfer is therefore NOT established. The earlier
48-row-to64-row learning-curve transfer remains an unverified model assumption;
compilation cannot repair it. Root refusal is a research decision, never a new
production safety permission.

This reuses the historically examined mmBERT/AG News 64/32/32 archive. There are
no new sources, new source families, fresh Encoder calls or future time windows.
Different modes/scenarios/repeats are NOT independent tasks. Attempts to obtain
new source material in this session did not produce usable new container data;
no downloaded partial or webpage excerpt is used as experimental evidence.

## Real computation and cost

The formal run physically fits the original four empirical learning curves once
(512 SGD updates,16 internal scoring calls), compiles one shared asset and loads
it once. Every arm then owns a newly initialized1540-parameter Head and pays for
all of its actual online updates and calibration. No trained Head is shared
across comparison arms. This isolates shared CONTROL from shared MODEL weights.

Seven controls and four original scenarios with three rotated timing repeats
produce84 lifecycles. Compare shared neutral/NDU with the same on-demand solver,
and with zero-search fixed8/fixed32/no-update. Compare actual decisions, full
weights, loss traces, calibration IDs, heldout probabilities and durable event
order. Failure leaves no success seal. Time includes synchronous journal writes;
raw decision phases are reported separately. All records are self-observed in
an isolated host, not independently attested CPU/energy/latency measurements.

Per-method cold-start attribution includes the whole prior, compilation and load
as applicable. Physical campaign accounting counts each actually executed shared
setup ONCE, not once per hypothetical counterfactual method. These are different
accounting views and are never added together. Break-even call counts extrapolate
measured constant marginal costs and are NOT executed future workloads. Return
null when marginal saving is nonpositive. A hypothetical reuse horizon H does
not multiply real sample count or amortize setup cost.

Equal decisions under the same finite model prove neither new reasoning nor
reliable learned ROI. Even perfect reuse cannot turn a more expensive policy with
identical answers into a task gain over fixed8. Actual estimates are stored in the
observation/audit files, not in this normative source specification.

## Reproduction

Use Python3.13, NumPy2.3.5, single BLAS thread. Let NEWS_ARCHIVE be original
artifact11870475540 with SHA256195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7.
From the repository root:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news
python "$D/material_news.py" --archive "$NEWS_ARCHIVE" --output /tmp/shared-material
python -m unittest discover -s "$D/opportunity/compiled" -p test_compiled.py -v
python -O -m unittest discover -s "$D/opportunity/compiled" -p test_compiled.py -v
python "$D/opportunity/compiled/benchmark.py" --material /tmp/shared-material --output /tmp/shared-run
python "$D/opportunity/compiled/audit_compiled.py" --archive "$NEWS_ARCHIVE" --material /tmp/shared-material --run /tmp/shared-run --output /tmp/shared-audit.json
```

Use new paths; successful seals are never overwritten. The scalar reviewer
rederives all16 prior and relevant online checkpoints. The rational reviewer
checks all stored policy nodes. Both are separately implemented, same-author
reviews, not independent organizational acceptance. Full original tests and
source/merge hosted CI remain separate requirements. No main merge or promotion.
