# Captured paired trajectories for frozen System2 critics

Remote parent: `7cdd5380000051ce7f3ba9917a0092fbe7290e7d` (PR #1754).
Tested Python commit: `72c64d8d2bb9daa101a87d11af98b43baf2666f5`.
Delivery branch: `research/shared-stem-paired-trajectory-capture-20261014`.
Research-only. No main merge, production model selection or native installation.

## From manually prepared paired rows to executed segments

`paired_capture.PairCollector` now obtains the continuation endpoint and work
record by calling the EXISTING `system2_execution.run_reasoning`, not another
proposer/verifier loop or a fabricated high continuation value. Its explicit
PairedStart mode executes exactly one propose/verify pair, initialized with the
registered candidate and feedback. It cannot take an NDU policy or call a critic.
Thus the critic does not choose which registered observations enter its own fit.
Normal tuple-value, scenario-NDU and empirical-NDU paths remain compatible.

The stop endpoint is the supplied initial candidate; it is NOT regenerated.
Public task, candidate, feedback, declared prior verification rejection and origin
receipt must be registered before either utility is observed. Actual case hashes,
byte lengths, order, availability, fixed work policy/caps and first-party source
hashes are checked. Input rows have no utility labels. The origin receipt is a
link, NOT an authenticated extraction of the initial owner trace. Real operators
still need to supply that trace and validate its provenance.

The callback contract is read-only execution reconstructible from the public
boundary. Hidden mutable memory, KV state, stochastic environment state or tool
side effects are NOT snapshotted by this implementation. It does not create a
valid causal counterfactual for arbitrary stateful agents. Callback profile IDs
and Python object references do not establish honesty, statelessness or isolation.

## Complete records, separate scores, no retry selection

Each registered slot gets an exclusive numbered directory before callbacks.
STARTED.json, pair.json and a final synchronized TERMINAL.json retain the supplied
stop endpoint, actual continuation endpoint, callback trace, monotonic duration,
work record, source hashes and identities. Pair IDs never become directory paths.
An existing slot cannot be retried, even after a failure. Incomplete publication
remains unresolved; a recorded failed callback is a failed observation. Neither
can be discarded to improve a fitted table. Local exclusivity is not a globally
authenticated experiment registry or a multi-writer recovery protocol.

`paired_capture_export.assemble_pairs` joins ONE externally pinned objective
receipt only after ALL registered pairs have terminal records. Every utility
names its exact stop/continue output hash, common objective and observer. Verifier
acceptance is NOT a utility label. Tests explicitly accept a wrong answer in the
verifier while the separate arithmetic oracle gives it zero utility.

For a failed continuation, delivered utility is zero under the existing fail-
closed estimand. Its actual known work prefix remains in pair.json. Unknown or
failed scope coverage is not converted into complete arithmetic work; normalized
rows retain null, and the unchanged fit_critic rejects the ENTIRE fit. Observed
envelope violations also reject the whole fit, not merely the expensive rows.
The export CLI writes all normalized rows and lineage before attempting fitting,
and writes FAILED rather than a release marker when fitting rejects.

This profile's in-process ATen formula work covers the additional callback pair.
The monotonic duration includes instrumented single-segment execution/reporting.
Initial candidate generation, collection registration, most file/source hashing,
publication, external scoring, external process/API work and energy are not thereby
complete system costs. This increment does not compare cost-matched systems or
make calibration-data acquisition free. Clock inconsistencies/expired captures
are fenced rather than converted into positive-duration evidence.

## Bind captured data to the critic that consumes it

`fit_collected` reuses the existing grouped fitting/calibration algorithm, then
produces critic artifact V2 with the capture ID, complete terminal inventory,
raw common observer receipt, source inventory, normalized dataset and arithmetic
profile. Its runtime FrozenPairedCritic rejects a different arithmetic profile;
cost coefficients cannot silently act on another formula unit. Old artifact V1
and old receipts keep their previous layout when capture binding is absent.

Artifact binding remains content linkage, not source signing or observer
independence. The statistical target is still the previous conditional bin-average
net gain, not a pointwise guarantee or proof of transport to new problems. The
runtime horizon is still two rounds/five calls. No new neural critic, generation
model, FBSDE solver or nine-arm matrix NDU activation is included.

## Entry points for an admitted owner adapter

Freeze the existing paired_critic protocol with complete case fingerprints and
fit/calibration groups. Call freeze_capture with its actual public boundaries and
work policy/caps, then create_capture. Construct PairCollector using admitted
propose/verify callbacks and the matching callback profile. Invoke run_pair once
for every registered pair. An operator must independently retain the registration
and terminal IDs. Do not give the collecting process the later utility labels.
The full executable calling convention is exercised in test_paired_capture.py.

After external scoring and pinning its RAW file SHA256:

```sh
python qualification/stem-cell-v1/paired_capture_export.py \
  --capture-dir captured-pairs --capture-id "$RETAINED_CAPTURE_ID" \
  --observer external-objective-scores.json \
  --observer-sha256 "$RETAINED_OBSERVER_SHA256" --output new-critic-release
```

The output includes paired-rows.json, lineage.json, critic.json, fit-work.json
and a release marker only on success. Fit/runtime examples are in the integration
tests. Their values and callbacks are test fixtures, not recommended thresholds
or authenticated operational data. To replay a capture, use its exact source
version: source hashes are part of registration, not a claim of cross-version
compatibility.

## Actually observed tests and diagnostic

The unchanged parent source slice passed 314 distinct tests. Final exact source
passed 342 distinct tests twice, zero failures/errors/skips: 314 retained plus
12 capture and 16 export/fitting/control tests. All seven uploaded Python blob
hashes match locally tested bytes. Compileall and diff whitespace passed. Tests
include actual callback dispatch, mutations, no retries, failed publication,
score ordering, endpoint substitution, failure/cost retention, over-envelope
refusal, contradictory rehashed work, runtime profile mismatch and CLI release.

A 60-pair diagnostic executes procedural arithmetic and real CPU tensor operations:
42 normal pairs produce a fitted critic and a later five-call revision; six
verifier-accepted wrong outputs receive zero external utility; six provider
failures retain incomplete work and prevent fitting; six 107-formula-operation
segments exceed their fixed 100-operation envelope and prevent fitting. The 60
pairs used 114 capture callbacks; the later NDU invocation used five more.
These are NOT pretrained-model experiments or independently authenticated outcomes.
Initial candidates, group IDs and logical clocks are test fixtures; arithmetic
labels come from a separate test oracle. Full raw endpoints, traces, scores and
work observations are retained in the package, not just this summary.

One development test used a synthetic clock advancing slower than actual first-
call initialization, and was correctly rejected by the chronology check. Only
the test clock was corrected to include elapsed monotonic time; the production
chronology gate was not relaxed. Two earlier baseline commands hit the tool's
execution timeout; the separate completed baseline log passed all 314 tests.
Those interrupted logs and the genuine development failure remain in evidence.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

The separate installed-HF attempt failed at import: Transformers is absent and
none of its three checks executed or was counted as passing. Direct GitHub/model/
package DNS also failed locally. GitHub publication used the connected API.
No approved pretrained weights/task data, project cloud, GPU/native service,
full-repository/Rust or hosted-CI result is claimed. The local workspace is a
bounded source slice, with no full codex-rs checkout or just for repository fmt.
Remaining acceptance includes real owner boundaries and callbacks, authenticated
independent scoring, credible conditional cohorts and final outcomes, complete
acquisition/inference cost comparisons, native ownership/recovery, multimodal
learning, multigeneration retention and 1024/4096-Cell qualification.
