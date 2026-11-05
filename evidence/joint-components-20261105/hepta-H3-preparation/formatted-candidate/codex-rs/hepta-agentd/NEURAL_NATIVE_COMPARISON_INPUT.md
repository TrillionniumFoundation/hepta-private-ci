# Explicit runtime input for the controlled native comparison

The opt-in `neural_comparison_native` integration test accepts
`hepta-smollm-neural-comparison-native-v2` through
`HEPTA_PN3_NEURAL_COMPARISON_CONFIG`. The v1 input is rejected. Adding an empty
snapshot, capturing the current environment at load time, or deriving a new
expected digest from the file being admitted does not migrate an existing input.

An operator must provide an already retained v2 cold-runtime snapshot and its
independently fixed SHA256, together with the existing parent and model inputs.
The comparison reads this snapshot once before it creates its comparison ledger
or starts either worker. Both models receive these same bytes. The snapshot file
must be a canonical absolute regular file, nonempty and at most 16 MiB; its bytes
must match the supplied nonzero digest. The snapshot schema is
`hepta-controlled-cold-runtime-snapshot-v2`. Original worker admission still
checks its interpreter, installed inventory and runtime files before execution.

## External input contract

Every path below is absolute. The snapshot path is also canonical and must not
be a symbolic link. The three SHA256 fields are the previously retained digests
for their respective exact files. The output directory must be new, as required
by the original comparison.

```json
{
  "schema": "hepta-smollm-neural-comparison-native-v2",
  "python": "/operator/runtime/bin/python",
  "runtime_snapshot": "/operator/retained/runtime-snapshot-v2.json",
  "runtime_snapshot_sha256": "REPLACE_WITH_INDEPENDENTLY_RETAINED_SHA256",
  "chain": "/operator/fixed-chain-checkout",
  "materials": "/operator/complete-model-materials",
  "baseline_parent": "/operator/retained/baseline-parent.json",
  "baseline_parent_sha256": "REPLACE_WITH_RETAINED_BASELINE_SHA256",
  "candidate_parent": "/operator/retained/candidate-parent.json",
  "candidate_parent_sha256": "REPLACE_WITH_RETAINED_CANDIDATE_SHA256",
  "output": "/operator/new-comparison-output"
}
```

This template deliberately cannot run until the operator supplies the real
paths and fixed digests. The input consumer neither creates a runtime snapshot
nor supplies an operator root, grant, qualification or replacement model.

The existing separate producer is `scripts/hepta_smollm_runtime_snapshot.py`.
Its `record --lock --installation --output` command requires the original locked
CPU requirements, their complete installation report, and a private CPython
3.12 environment launched with `-I`. It records the selected interpreter,
installed files and preflight imports and emits the snapshot's SHA256. An
operator may retain that result as an independently fixed input before a
separately authorized comparison. The producer explicitly records
`immutable_held_runtime_closure=false`, `actual_model_execution=false`, and
`production_qualification=false`; recording or verifying a snapshot does not
establish any of those qualifications. The comparison does not invoke this
producer or replace an already pinned digest when an input disagrees.

The comparison's execution profile binds the complete current set of 13 Chain
source and configuration files: `contract_wire.py`, `devnet-v1.json`,
`ledger-v1.json`, `model-family-v1.json`, `work-profile-v1.json`,
`llm_adapter_contract.py`, `llm_base_material.py`, `llm_inherited_runtime.py`,
`llm_neural_read_worker.py`, `llm_parent_material.py`,
`llm_python_runtime_contract.py`, `llm_runtime_pilot.py`, and
`model-family-smollm2-135m-v1.json`. It no longer constructs the obsolete six-file
profile. The original profile verifier checks this complete set and the worker
checks the pinned source bytes.

## Scope and retained failures

The real gen2/gen3 comparison remains ignored by default and requires explicit
operator inputs. The new input-contract control uses inert local fixtures;
it does not execute Python or a model. The existing untrusted-qualification
control deliberately supplies an unavailable empty snapshot and must still
reject at the original qualification boundary before creating runtime owners.

This migration does not authorize a new learning trial, reset a spent ledger,
change tasks or baselines, or turn the controlled comparison issuer into product
authority. A prior failed or spent comparison is retained. Model adoption and
independent qualification require their own current authorized inputs and
ordinary execution evidence.
