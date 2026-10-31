# HCSN: causal action and process verification, 2026-10-31

This experiment continues the exact R9 source at
`e7eaa5e0be835269636216c8fe8b1ae2f1a22361` (tree
`2182eb6fd29f615a9110e4b84103f1d7e254c41d`). It preserves R9 evidence.

The five acceptance questions are: executed process fidelity; decisions before
content reads; task-value boundaries under identical resources; analytic versus
ordinary/matched-C1/CfC controls; and transfer to real paired audio/video.
Positive scientific conclusions are not presumed. Each package records its
own source, assumptions, execution evidence and unresolved claims.

## Concrete baseline discrepancy

R9 `Owner::interval` decodes caller-selected content before advancing the cell.
Its already-measured commit batching gain leaves decoder calls unchanged.
The new native task owner selects READ/WAIT/STOP using visible state before a
content request is passed to the existing FullHX decoder. The task contract,
counterfactual teacher and runtime will be checked against one another.

## Source combinations

- R9 owner and FullHX fixture: the commit above.
- Actual Hepta runtime dependency sources: `732e934ba496d90fbe042b8d41d479ef901643e5`;
  every source blob is recorded in `integration/UPSTREAM_NATIVE.json`.
- Real CREMA-D feature data: `dca9febc8143c682077fe27d40dbeaa1137bcaa4`;
  data-specific provenance is recorded by the AV package. Its whole-clip
  resampling is an offline representation, not a causal streaming decoder.
- New verification and adaptation code: this directory and the corresponding
  commit. Results from another branch are never counted as this run's evidence.

## Clean native build

`integration/prepare_native.py` restores the exact original sources into an
isolated workspace, verifies Git blob identities and generates a small enclosing
Cargo workspace with fixed direct dependency versions. The original crate
manifests are unchanged. Generated Cargo.lock, compiler identity and input hashes
are retained. No previously compiled dependency artifact is accepted as proof of
a fresh build. The scoped `HCSN causal five track` workflow runs this build and
the new native qualification when its implementation is present.
