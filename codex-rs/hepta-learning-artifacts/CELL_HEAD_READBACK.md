# Persisted Cell Head readback

This boundary connects real offline Head bytes to the existing immutable artifact
owner. It adds no writer or selector. `LearningArtifactOwnerService::publish`
continues to own publication, durable checkpoints, writer leases and CURRENT.

`read_current_artifact` requires independently retained publication, V3 admission,
publication predecessor, current registry head and current withdrawal head pins.
It revalidates the source datasets against the owner's installed withdrawal
frontier, recovers the acknowledged publication and verifies the signed CURRENT
snapshot before opening the persisted payload. The result has private fields.
The caller must read again before each use; a saved result cannot establish
continued revocation freshness. The owner still requires a trusted host to supply
authenticated withdrawal updates, signed head freshness, and its storage root.

`verify_cell_head_bundle` consumes that read and independent export identities. It
checks the original JSON and NPZ byte digests, bounded framing, feature identity,
training-code and runtime identities, exact training/calibration dataset inputs,
and the full owner manifest's matching provenance. It returns a private
`VerifiedCellHeadBindingV1` with the original bytes and owner evidence. Rust does
not parse NPZ tensors or execute the Head. The exporter verifies their full
inventory, shape, dtype, finite values and P37 tensor-state digest. Independent
retained identity pins and the publisher's authenticated attestation remain
essential; an arbitrary caller-supplied digest is not evidence of training.

## Frozen specimen and regeneration

The fixture is the actual Granite linear Head from immutable commit
`dac730dc8ddbd96d87f6dc0c5eb94d3436d90a2b`, under
`qa/stem-bakeoff/evidence/20261022-real-model/granite-heads/linear/`.
Its original manifest and NPZ are copied unchanged. `pins.json` records their
digests, the run-report digest and the derived research input frontier. The
export also verifies every training-code file against the original run plan.

From the repository root:

```sh
python3 codex-rs/hepta-learning-artifacts/tools/export_cell_head_bundle.py \
  --repository . \
  --revision dac730dc8ddbd96d87f6dc0c5eb94d3436d90a2b \
  --output codex-rs/hepta-learning-artifacts/tests/fixtures/p37-head
python3 -m unittest discover -s codex-rs/hepta-learning-artifacts/tools -p 'test_*.py'
```

The bundle framing is magic `HEPTA-CELL-HEAD-BUNDLE-V1\0`; five feature digests;
three little-endian u64 values (encoder generation, revocation epoch, width);
eight identity digests in the order of `CellHeadBundleIdentityV1` after `feature`;
two little-endian u64 byte lengths; original manifest bytes; original NPZ bytes.
The native file digests use SHA-256. Checkpoint, scope and purpose digests hash
their exact UTF-8 strings. Feature compatibility is SHA-256 of the feature
portion prefixed by `hepta.cell-head-feature.v1\0`.

The source frontier hashes the exact training and calibration input receipts,
including label, source-group, source-record and feature-bundle digests. It is a
research cohort identity, not an authenticated production memory ledger. Future
and OOD evaluation labels are not training inputs. The changing forget frontier
comes from the fresh owner withdrawal view, not from this static bundle.

The standalone exporter rejects reports carrying an `evolution` lineage. A
split, continued, or merged Head inherits its ancestors' training and calibration
sources, including Router learning. Its latest local replay is not the complete
source closure. Importing those descendants requires a separately versioned
closure contract and owner validation; deleting the evolution declaration is
not an authorized conversion. Offline evolution remains outside this native
bundle's supported provenance format.

The native tests publish and reopen the real bytes, and reject disk corruption,
wrong identity, old predecessor/current pins, mismatched owner provenance and
subsequent dataset withdrawal. Their signing key and device/objective identities
are explicitly test-only. Encoder generation 1 and Head owner generation 2 are
separate. These tests establish artifact custody; they do not claim memory-task
improvement, independent scientific evaluation, production authority, or Head
execution inside Rust.
