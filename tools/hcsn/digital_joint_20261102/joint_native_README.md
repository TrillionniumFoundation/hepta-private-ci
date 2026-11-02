# Native execution and interruption qualification

There are two separately identified execution stages here. The transaction
prototype wraps the archived 17-state native owner. The additional
`hepta-digital-joint-native` crate executes `joint-policy-v1` with the new
43-feature, fixed-deadline/current-at-due task, full 33-state conditional mass,
reset-aware forecast bank, and the exported 64-unit GRU. Neither stage activates
production authority or establishes a task-utility advantage.

## Real nextest gate

`joint_native_gate.py` records the unchanged four-crate `just test` command
before and after adding the real official `cargo-nextest 0.9.150`. Before fails
with missing nextest; after reports **178 passed, 1 skipped**. No helper is
replaced, and no direct-test fallback is counted as a passing nextest gate.
The official artifact metadata and SHA256 are in
`evidence/joint_native_nextest_official_artifact.json`: repository
`nextest-rs/nextest`, CI run `40376183688`, artifact `12675620675`, commit
`d225b1daf362c1ca8e5e048132618c1a81c57a28`. The ZIP SHA256 is
`aebbb3ce81eaf1f92ae3b4e7c30919dc35d8d84b0cf04518f5c270b89cb87d0c`;
the extracted real ELF SHA256 is
`7e43165f5360b31ac559113848e56e1cf0dc97014d34fbbdfa62741754740435`.
Its executable version/commit were actually checked. The direct release URL
timed out through the configured proxy; the supported GitHub artifact transfer
and permitted returned file host were used without changing or bypassing it.

## Build and replay

Restore the 60 inherited runtime source files and four repository gate helpers
as described in `../digital_read_followup_20261101/NATIVE_README.md`.
Set `REPO`, `WORK`, `RUST_BIN`, `TOOLS_BIN`, and `CARGO_CACHE` to local absolute
paths. Use the actual Rust 1.95.0 toolchain; `TOOLS_BIN` must contain genuine
`just` and `cargo-nextest`. Python requires NumPy/SciPy, while deployed joint
inference imports `joint_deploy.py` without Torch.

```sh
cd "$REPO"
python -m tools.hcsn.digital_joint_20261102.joint_native_full_build --upstream-root "$WORK/upstream" --work-dir "$WORK/joint-full-native-build" --rust-bin "$RUST_BIN" --tools-bin "$TOOLS_BIN" --cargo-home "$CARGO_CACHE" --receipt "$WORK/joint_native_full_build.json"
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_native_full_qualify --binary "$WORK/joint-full-native-build/codex-rs/target/release/hepta-digital-joint-native" --out "$WORK/joint-native-replay"
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_native_artifact_audit --models "$WORK/joint-native-replay/models" --out "$WORK/artifact-audit.json"
```

The new crate retains the entire old native test crate and all runtime tests;
its real five-crate gate reports **179 passed, 1 skipped**. The build receipt
binds all generated Rust files, both crate manifests, actual workspace/lockfile,
golden fixtures, inherited Git identities and builder sources. Exact-anchor
overlays fail if an inherited source no longer matches. No frozen old namespace
is modified. The recorded FullHX fixture uses original Git blob
`38ad00490ee921834d05667323372da36cfc5ef4`, SHA256
`66bb4fabc2fdca0b08d7e834f6a1dfdd73aedb4cfbd1b4c594b709f742092972`.

## State, time, and failure boundaries

The joint owner stores every completed observation with its due boundary and
persists all 33 mass and nine forecast coordinates. Recovery reconstructs CTMC
or GRU state from the complete observed prefix/public schedule and checks it
against that stored memory. There is no hard latent-cell RNG substitution.
READ at tick 0 with delay 2 opens packet slot 1 at boundary 2; its observation
uses boundary-2 reliability. Decisions run through the actual `NeuronModelPort`
before any due packet open, then actual bounded FullHX inference produces the
completion. The target remains the sign at deadline 6, including early submit.

`joint_native_owner.py` publishes a complete native generation by an atomic
pointer after file/directory fsync. Each request binds its parent external ACK,
request id and action count. Unprepared failed children are quarantined without
rolling back the acknowledged native witness. Prepared durable IO receipts are
reused; a crash after publication but before its reply returns the same commit
for the same request id. Missing/stale ACKs, reused request contracts, changed
generation payloads and changed prepared receipts are rejected.

Abrupt-exit hooks occur after a real native tick, due READ, child checkpoint,
durable prepared receipt, generation move and publication. Before a prepared
receipt, read-only packet opens/FullHX may repeat: qualification explicitly
observes two physical executions in such cases. The once guarantee is one
published logical successor/fee ledger per request id. It is not an arbitrary
external-side-effect exactly-once or hardware power-loss guarantee. Prepared
retry tests remove the original due packet and verify that no child is rerun.

## Interpretation of evidence

The joint owner qualification uses hand-built excluded engineering worlds and
untrained exports from all four supported families. It checks full episodes,
current-at-due actual reads, conditional memory, cold ACKs, interrupted pending
actions, plausible mass tampering and unread-payload blindness. These are
implementation results; use separate frozen confirmation for scientific utility.
The older 17-state crash results are retained separately and cannot be borrowed
as evidence for joint33 execution. Failed development attempts remain archived.

Rust validates generator and transition-table shape/admissibility separately.
`joint_native_artifact_audit.py` independently checks each supplied concrete
table against SciPy `expm(dt*Q)`; this is not a universal malicious-artifact
relationship proof. `ru_maxrss` is a measured whole-process peak, including
model tables/FullHX. The inherited `transient_allocation_bytes=4096` is an
unqualified estimate, not a measured allocator value or a proved upper bound.
Production ownership, general continuous-boundary qualification, and the full
quality/latency/throughput/energy adoption gate remain separate requirements.

After the 20 actual final models and `MODEL_FREEZE.json` are remotely published,
qualify those weights separately on each fit's first two existing validation
worlds; the engineering fixtures do not qualify the final weights:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_native_frozen_weights_qualify --formal-root "$FORMAL_ROOT" --binary "$WORK/joint-full-native-build/codex-rs/target/release/hepta-digital-joint-native" --published-model-commit "$PUBLISHED_MODEL_COMMIT" --out "$WORK/frozen-native-weights"
```
