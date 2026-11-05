# Complete frozen scientific replay

The root reviewer reran the complete frozen experiment in a new process and
directory. This includes source/input identity checking, all five fits, target
and feature generation, direct and projected-gradient solving, 160 validation
worlds, gate selection, and 320 TEST worlds. It is a replay of the same
implementation and already-exposed schedules, not a second independent
statistical confirmation or a new implementation of the scientific model.

`PROTOCOL.json` and `compare_replay.py` were frozen at
2026-11-05 01:20:47 UTC, before either invocation. The comparator SHA256 is
`edfa022d6e9b23c352cae322a3a9282f31552401da03fde686897f24197424a6`.
The original scientific protocol and all candidate/gate/numerical settings were
unchanged. The comparator excludes only eight explicitly named trajectory
resource fields and three summary resource fields. All compared scientific
JSON values must be exactly equal, with no numerical tolerance.

## Results

The complete second invocation exited zero. Its independently observed worker
cost was **467.784030 CPU seconds**, **470.209338 wall seconds**, and
**197,976,064 bytes peak RSS**, including imports and final writes. The
independent record verifier then passed; its full child cost was 10.786752 CPU
seconds / 12.965658396 wall seconds. The exact comparator also passed, using
5.492760 CPU seconds / 5.905558505 wall seconds. These are separate child
processes; their controller measurements are retained separately and stop
before the controller's final receipt write.

All **77 comparisons** passed: 35 serialized model JSONs, 20 complete world
files, 20 trajectory-result files, the scientific summary and the frozen
gate decisions. Primary intervals, candidate restoration, qualification flags,
own-law table hashes and all nonresource trajectory diagnostics are unchanged.
The original structural gain and pure-head-edit failure reproduce exactly.

All rerun artifacts are retained in [attempt_2](attempt_2). The original worker
receipt is [PROCESS_RECEIPT.json](attempt_2/PROCESS_RECEIPT.json), verification
receipts are in [ACCEPTANCE_PROCESS_RECEIPT.json](attempt_2/ACCEPTANCE_PROCESS_RECEIPT.json),
and the full pairwise comparison and rerun-file manifest are in
[COMPARISON.json](attempt_2/COMPARISON.json).

## Retained failed invocation

The first invocation used a nonexistent local joint-source directory. It failed
before input/source checks and model evaluation, with **1.142841 CPU seconds**
and **1.143709832 wall seconds** measured for the full child. The corrected
invocation uses the already-present `frozen_joint` directory; no scientific
setting, source, candidate, seed, radius, stopping rule, or comparison tolerance
changed. The failure, original stderr hash, path-redacted log and correction
record remain in [attempt_1](attempt_1). It is an orchestration failure and is
included in the known cost, not reported as a successful experiment.

## Verify included outputs

From this directory in a checkout containing the stacked original package:

```bash
python ../ndu_policy/verify_records.py attempt_2/run ../ndu_policy/PROTOCOL_FROZEN.json \
  --history ../../wsp_20261104
python compare_replay.py ../ndu_policy/execution_r1/run attempt_2/run comparison_new.json
```

`comparison_new.json` must not already exist. The first command performs
independent record arithmetic and binding checks; the second compares stored
results. Neither command repeats model execution. For a new complete run,
follow `../ndu_policy/README.md`, use a new output directory, and pass its `run`
subdirectory to these same acceptance commands. Timing need not match the
included run; it must remain recorded and excluded only under the frozen
explicit field list.
