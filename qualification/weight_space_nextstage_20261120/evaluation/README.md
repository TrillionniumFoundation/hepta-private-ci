# Bounded research evaluation and finite net-value decisions

This is a read-only Python standard-library research adapter. It does not train,
edit, publish, adopt a model, send a broker order, or claim a general NDU optimizer.
Every output has `production_eligible=false`. The default decision is
`KEEP_ORIGINAL_AND_STOP`; complete evidence can only yield
`RECOMMEND_RESEARCH_CANDIDATE` within a predeclared finite candidate list.

## What is authenticated

An experiment owner or reviewer must supply the SHA-256 of `owner.json` outside
the candidate request. That file pins the protocol, separately acquired clock,
original model registry, graph, task, input schema, label source, objective,
semantics, candidate seal, raw sample content, label availability receipts,
exposure history, outcomes, costs, and every original/candidate model artifact.
The evaluator reads and hashes the actual files, checks each linked identity,
and works on the resulting immutable byte snapshots. No caller-provided
`independent=true`, `fresh=true`, or `eligible=true` field is accepted.

This is authentication relative to reviewed local pins, not a signature of a
remote producer. The owner must independently acquire and review the clock,
label-source and training receipts, graph semantics, and scoring implementation.
A hash does not prove that those statements are scientifically true. Source
semantics and the graph are bound, but this adapter does not execute or prove
their meaning. Runtime semantic authentication is a separate necessary gate;
it does not establish independent labels or efficacy. Serialized JSON is not a
capability token. No output grants production authority or external holdout
custody.

The `clock.curr_time` receipt treats its second-resolution UTC time as a lower
bound, with an explicit uncertainty interval. The normal CLI does not accept a
caller-supplied current time: local system time must be consistent with the
unexpired pinned observation. Source and label ages use the conservative end of
the interval; labels must already be available at its lower end. The injectable
time used by unit tests and `demo.py` is explicitly synthetic.

## Evaluation contract

The protocol fixes the candidate set, independently trained fit registry,
domains, minimum gains, utility bounds, unit, statistical assumptions, prospective
sample rules, costs, horizon and resource conversion before confirmation.
Candidates and any development selection are sealed before sources for
confirmation samples are generated. Actual content hashes identify samples;
TRAIN, SELECTION, DISCOVERY and previous-confirmation overlaps are rejected.
An availability receipt must bind each label to its sample and timestamp. Every
sample must have one original and one outcome for every candidate; omissions,
duplicate IDs, unknown values, or model mismatches fail closed. All fit/domain
cells must have equal, nonzero sample counts.

The statistical unit is the independently trained model fit, not a state, world,
row, repeated forward pass, or multiple random patches of one checkpoint. Unique
training seeds, run receipts and original checkpoint bindings are required.
Uniqueness is provenance evidence, not a proof of independent errors. For paired
Student-t intervals the protocol must state the conditional independence and
approximately normal fit-level difference assumptions. Five fits mean `n=5`,
`df=4`, even if there are 160 worlds. A Hoeffding option instead uses bounded
independent fit-level differences, with full difference range twice the utility
span; it is often much more conservative.

For `M = candidates × domains`, each two-sided interval uses alpha/M. The
weighted combination of simultaneous domain lower bounds is also a conservative
lower bound for the predeclared nonnegative domain mixture. Diagnostics
requiring privileged oracle interventions can be evaluated but cannot be
recommended as deployable weight candidates.

## Finite decision objective and units

Let `L[c,d]` be the simultaneous lower bound on candidate-minus-original mean
task utility per episode in domain d, `w[d]` the fixed domain mixture, `H` the
fixed number of future episodes, and `B[c,r]` an owner-pinned upper bound on the
candidate's incremental future resource cost over that horizon. An explicit
conversion `lambda[r]` must express task utility per resource unit. The adapter
computes:

`net_lower[c] = H * sum_d(w[d] * L[c,d]) - sum_r(lambda[r] * B[c,r])`.

The episode count is dimensionless; task utility has the same declared unit on
both sides. A resource second, byte, token or currency amount is never directly
subtracted from a task score. The conversion is a declared owner preference,
not an empirically discovered scientific constant. Future resource bounds are
also explicit assumptions; already-spent training/editor/evaluation cost is a
sunk measurement and cannot be substituted for this future cost.

A candidate is admissible only if every domain lower bound exceeds its fixed
minimum, all costs are measured/bounded with no missing components, all units
match, and net lower value is positive. Among this fixed admissible list only,
the largest net lower value wins, with deterministic candidate-ID ties. This is
neither weight-space global optimality nor a theorem that running another search
has negative value. STOP is the action justified by the finite authorized
evidence and budget; an unknown future benefit is never treated as positive.

Missing conversion or horizon yields `net_value_lower=null` and STOP. The output
still provides a Pareto set and one-resource break-even sensitivity, explicitly
conditional on other costs being zero. Unknown cost is not treated as zero.

### Version 2: retained quality with cheaper computation

`hepta.finite-evaluation-protocol.v2` is an explicit extension for candidates of
kind `compute_specialization`. It replaces `minimum_gain` by a nonnegative
`maximum_quality_loss` fixed for every domain before evaluation. Each simultaneous
quality lower bound must be at least the negative of this tolerance. Thus an
equal-quality candidate can qualify without inventing a positive model-quality
gain. Quality below the frozen tolerance is rejected regardless of savings.

Version 2 costs bind exactly the same `horizon_episodes` as the protocol. They
contain a common `original.resources_lower_bound` and each candidate's
`resources_upper_bound`, plus explicit basis and unmeasured-component fields.
All resource coordinates must match. The conservative incremental resource
cost is `candidate_future_upper - original_future_lower`; it can be negative.
Multiplication by a nonnegative, explicitly declared task-utility conversion
then makes guaranteed savings a positive contribution to the lower net value.
Missing bounds, missing resource coordinates, unknown components, a horizon
mismatch, or past timing supplied as the bound basis all stop qualification.
No baseline unknown is silently replaced by zero.

The complete synthetic version-2 example keeps quality exactly equal, assumes
an original future CPU lower bound of 100 seconds and an EDIT upper bound of
10 seconds, and explicitly sets the conversion to .01 synthetic utility per
CPU second. Its conditional lower net value is .9 synthetic utility and EDIT
is recommended for research. The WEAK candidate's assumed upper bound is 60
seconds and has lower net value. These are fixture assumptions, not measurements
of Hepta or claims about future hardware. Removing the baseline bound or
conversion produces STOP. The additional ten tests include these branches,
quality deterioration, missing horizon, mismatched horizon, and noncomparable
resource units.

Run `python -m unittest test_evaluation test_specialization -v` for all 40 tests
and `python demo_specialization.py` for the explicit synthetic cases.
The demo writes its complete synthetic results to stdout. Captured execution
receipts are retained separately. Version 1 behavior remains unchanged.

## Running the self-contained qualification tests

This source-only package contains no actual host snapshots, private model
parameters, deployment metadata, source pins or research outcome datasets.
Python's standard library is sufficient; no model runtime, service access or
network connection is required.

```sh
python -m unittest test_evaluation test_specialization -v
python demo.py
python demo_specialization.py
```

The fixtures create temporary owner packets and explicitly use a deterministic
synthetic clock. They validate reachable decision branches and malformed-input
rejections; they make no model-quality or live-data claim. For reviewed real
inputs use the normal CLI without a clock override:

```sh
python evaluation.py --root /absolute/evidence/root --owner owner.json --owner-sha256 REVIEWED_SHA256
```

The owner SHA is a separate trusted input. A candidate must not be permitted to
replace that input or supply a new owner manifest as its own authorization.
The adapter does not provide a remote signing service or an approval bypass.

## Bounded inputs

Each file is limited to 8 MiB, total core artifacts to 32 MiB, samples to 4096,
fits to 64, candidates to 16 and domains to four. JSON rejects duplicate keys,
nonfinite or out-of-range numbers and excessive depth, node counts and strings.
Files must be regular files; nonblocking/no-follow open rejects FIFOs and
final-component symlinks. Relative paths cannot escape the configured root
when resolved. This is a pinned local-data reader, not an operating-system
sandbox against concurrent parent-directory replacement. Hashes authenticate
content relative to trusted pins; they do not prove collection custody,
semantic correctness, a remote clock or unrecorded exposure history.
