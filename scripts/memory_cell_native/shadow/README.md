# Controlled pretrained v2 shadow qualification

This separate probe adds one real, fresh Python decoder process to a completed
v1 development run. It reuses the exact trained adapter, base, lineage, source
document and 96-update recipe. It does not rerun training, tune an answer, replace
the v1 control-socket probe, or remove the base/shuffle/fresh-process controls.

The executed path is `AgentdNativeMemoryCell::shadow_owner` →
`AgentdNativeMemoryShadowOwner::read` → `NeuronRuntime::tick_shadow` →
`NativeMemoryModelPort` → actual Python v2 worker → journal/witness commit →
source completion → delivery revalidation. This v2 example calls the owner
directly; it does not claim to exercise a v2 control-socket ingress.

## Registered changes and explicit limits

- The original v1 config remains unchanged. Its width is 4; the sparse kernel
  requires at least 5. A separately named shadow profile uses width 5, with its
  own config/profile digest and process-receipt directory. Decoder prompt,
  sampling behavior, rank, seed and weights remain unchanged.
- A checkpoint from an older v1 runtime may be reused. The runner explicitly
  registers the current repository path and measured runtime/worker hashes in
  the new config and retains the full old→new diff. Every other pin must remain
  identical, including base, adapter, lineage, tokenizer and launcher.
- `ControlledQualificationContext` is a named qualification provider. Objective
  and NDU hashes come from separate retained qualification documents; their
  contents are rechecked on every context read. They are not source hashes and
  do not represent production Objective/NDU authority.
- One actual `Instant` origin is shared across both owner recoveries. This is
  same-process recovery. Cross-process clock epochs remain unqualified.
- There is no calibration artifact, measured ECE, OOD estimate, or calibrated
  signal. The shadow observation always abstains and grants no authority.
- Local private journal/witness files are independently opened and verified;
  independent operational witness custody remains unqualified.

## Qualification sequence and retained evidence

1. Open a new real durable source owner and import the exact source document.
2. Run one native v2 callback; retain raw prompt/text/tokens, execution/source
   receipts, full actual tick binding and measured callback counts.
3. Close the shadow owner and read back actual journal/witness anchors through
   the public anchored APIs. Derive the expected namespace from the admitted
   source and registered profile, independently of the witness header.
4. Recover and retry the same nonce. Require the durable `Source::Replay`
   variant and no additional model callback. Drop that failed owner.
5. Recover again and require successful delivery of the original result before
   withdrawal. Perform real `forget_with_kg`, then require refusal identifying
   the changed source head while the writer authority remains valid.
6. Require unchanged model-callback counts and journal/witness bytes through
   replay, recovery and withdrawal. Verify all original v1 and checkpoint bytes
   remain unchanged. Retained raw output is audit history, not current support.

After the repository's scoped tests, root builds the example and runs:

```bash
cargo build --locked -p codex-hepta-agentd --example native_memory_shadow --features qualification-cognitive-write
python -I -B scripts/memory_cell_native/shadow/native_shadow_ci.py --repo REPO --binary BINARY --native-run COMPLETED_V1_RUN --out NEW_OUTPUT --expected-head COMMIT
```

The Cargo command runs from `codex-rs`; the Python command runs from the repo
root. CI runs this stage separately after the unchanged v1 probe and before
final lint/format proposals. New candidate source and binary hashes are retained.
Success adds one decoder query and one explicit feature forward, with zero
training updates. Autoregressive internal forwards are not fully counted here.

Engineering success is separate from the one-row exact-text observation. There
is no accuracy gate, unseen-task result, production acceptance, automatic daemon
installation, physical parameter deletion, or eight-blocker closure claim.
