# Immutable caption-controls replay (exploratory only)

This candidate replays completed **post-hoc** cosine controls from source
`539d1d5e73f7c26ec170165e610b8570858b1e59`, run `40107527699`, artifact
`12579262528`. It is not new training of a Head, preregistration, independent
replication, a new primary acceptance gate, or a production qualification.
Original test headlines were known before the control protocol was frozen.
`DENY_ALL` and `production_activation_allowed=false` remain unchanged.

`evaluate.py`, `test_controls.py` and `PROTOCOL.md` are byte-identical to the
completed local controls. `bindings.json` freezes their hashes, eight consumed
inputs, all 110 original ZIP members, all 20 original ledgers, 15 original
research source files, original output hashes, runtime and budget. Those 15
source files match base `3cdb6e8b369d481f614914dd44bace9961f03bbe`; the replay
candidate must be a single child commit of that base, recorded at runtime with
its tree and all candidate file hashes. No existing workflow, threshold, split,
research implementation or original result is edited. Checkout depth is 2 so
the exact parent and changed-path checks are available. An always-run final
step retains available compact replay evidence even after failure, records
post-run head/tree, candidate/workflow SHA-256 and all 15 original-source
hashes, and requires equality to the captured pre-run bindings and clean
worktree. Missing pre-run evidence fails closed; git status alone is not used
as proof of source identity.

## Bounded execution

The sole trigger is a push to `research/dot-caption-controls-replay-20261025`
touching this directory or its dedicated workflow. There is no PR, dispatch,
schedule or cross-workflow trigger. Base source's 81 YAML workflows were
inspected: none has `create`/`workflow_run`; existing branch/tag push filters do
not match this branch. Do not open a PR as part of this replay.

Ubuntu 22.04, Python 3.12.14 and two isolated SHA-locked official NumPy CPU wheels:
1.26.4 for frozen controls; 2.3.5 for original derived-ledger validation;
BLAS threads = 1. Job ceiling 10 minutes, artifact download 90 seconds, two
control computations of at most 90 seconds each; ledger audit at most 90 seconds. The only fitting is the
already-defined one-dimensional cosine logistic train/dev/calibration fit.
No photos, model downloads, encoder calls, new datasets or original Head fits.

GitHub CLI retrieves only the original artifact through its normal API flow;
its host-change authentication guard strips credentials on redirects (official
[implementation](https://github.com/cli/cli/blob/trunk/api/http_client.go)).
Only `contents: read` and `actions: read`; no custom Authorization headers or
verbose HTTP traces. Download stderr is not published because it may contain
signed URLs. CLI version and executable digest are recorded, not pre-pinned;
the hosted runner image itself is not immutable. Download failure, expiration,
permission denial, digest mismatch or missing input stops the replay, without
mirroring, reconstructing, substituting data or relaxing checks.

Opaque ZIP size/digest precedes ZIP parsing; path, type, duplicate, method,
member/total-size, CRC and per-member hashes precede extraction. All eight
consumed input hashes precede JSON/NumPy parsing. Nested NPZ sizes and CRC are
checked; NumPy loading disables pickle. Original ZIP and extracted bytes stay
in runner temporary storage and are **not** committed or uploaded. Only compact
results, source/tool records and replay receipts are uploaded (14-day retention).

All 20 ledgers are validated with the **unmodified original loader** under
NumPy 2.3.5: reconstructed probability/prediction arrays and canonical digests
must match exactly; metrics and per-row values use the original independent
audit tolerances (relative 1e-11, absolute 1e-12). Original hosted runtime was
NumPy 2.2.6; the separate 398-check local audit used 2.3.5. This focused replay
does not claim to repeat all 398 checks. No original validation is disabled.

Two environments are necessary for the demonstrated numerical boundary. Under
1.26.4 the original loader rejects reconstructed derived-array bytes. Under
2.3.5 controls reproduce results/predictions, but frozen-fit.json differs in
last-bit intercepts of unselected regularization candidates (for penalty
0.0001: -0.07176986724002195 versus -0.0717698672400219). We do not rewrite frozen
outputs or relax original checks. Under 1.26.4 all three original controls
output SHA-256 values must match on both repeats. Cross-platform drift fails
closed. The candidate never substitutes raw hash/confusion checks for original
derived ledger validation.

## Interpretation

Calibrated cosine 250/256 equals the original linear Head; gated 251/256 differs
by one case, with a descriptive block-bootstrap difference interval spanning
zero. There is no demonstrated nonlinear/private-Head advantage. Retrieval
127/128 in a two-candidate set is a different decision task, not a better binary
classification score. Source-pair mismatch is not semantic contradiction;
pretraining contamination is not excluded. This is not evidence for a newer
model/run or production deployment. Images retain their individual BY/BY-SA
attribution obligations; no photo or model redistribution is authorized here.

Local replay requires the original ZIP and exact source files:

```sh
python qa/caption-controls-replay/replay.py --zip ORIGINAL.zip --repo . --ledger-python AUDIT_VENV/bin/python --output NEW_DIRECTORY
```

Run `test_replay.py` normally and with `-O`; the actual controls must run without
`-O`, since original research assertions are preserved, not silently disabled.
