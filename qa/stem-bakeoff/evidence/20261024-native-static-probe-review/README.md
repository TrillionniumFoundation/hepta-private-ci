# Native pretrained probe: independent static review

This review inspected 30 files from `f2144a2451e0ca03f8c91e0c30755970cc1e4867`.
Every reviewed file matched that commit's Git blob; SHA-256 and byte inventories
are in `source-pins.json`, with exact copies under `source/`. Four unrelated
working-tree repair paths were already modified and are recorded in the snapshot.
The review did not change the active checkout, run a model, compile Rust, or wait
for a hosted qualification. Its conclusions concern the inspected v1 path.

## Finding

No oracle-to-model substitution was found in the inspected native read path.
The original source value is used to train the adapter and to score the result.
The read RPC carries only invocation ID, typed key/role and deadline. Server code
constructs the question and admitted model request; the worker receives no source
value. Its returned text comes from actual autoregressive token generation and
tokenizer decoding, then travels through `execution.text` to the RPC result.

This is a source-level finding, not a successful model execution. The two previous
hosted runs, 40102780899 and 40103922428, failed their Rust stage and did not reach
the pretrained probe. Root reported the new local qualification still compiling
with no local probe launched. The newer hosted run 40144148314 was not polled by
this reviewer; its eventual model count must be established from its own receipts.

## Fixed recipe and expected successful-run counts

`native_trial.prepare` creates a fresh protocol with 96 completion-CE updates,
rank 8, seed 24031, learning rate 0.01, and one exact question template. Training
loads the retained typed document and calls `SourceMemoryCell.fit_sources` once.
The training implementation records optimizer steps, losses, source/example
visits, forward count, input/supervised tokens, trainable parameter count, adapter
delta, gradients and optimizer tensors. Native CI pins the protocol before
training and rejects changes afterwards; there is no automatic model retry.

| Quantity | Expected if all registered stages succeed | Observed by this review |
|---|---:|---|
| Training processes | 1 | No new execution |
| Optimizer updates / explicit training forwards | 96 / 96 | No new execution |
| Native backend dispatches | 1 | No new execution |
| Native explicit feature forwards | 1 | No new execution |
| Native adapter decoder queries | 1 | No new execution |
| Separate base-only / shuffled queries | 1 / 1 | No new execution |
| Total decoder queries | 3 | No new execution |
| Total model child processes | 4 | No new execution |

These are expectations from the fixed source. `backend_dispatch_attempts` is
incremented before subprocess launch, so it counts attempts including failures;
it is not by itself a count of completed decoder calls. On a partially failed
run, count actual completed work from retained stage/process receipts, not from
the all-success summary's constant `actual_decoder_queries=3`.

The selected fixed historical case is `covariance-diagnostics`. The target value
is the already exposed repair ID `order`, not an executable repair. Its source
archive and dataset hashes were independently checked without loading a model.
The derived question is 112 UTF-8 bytes, within the native 512-byte binding cap;
the actual tokenizer must still enforce the separate 192-token complete-prompt
cap. This one-source memorization probe does not execute or verify a repair task,
test future generalization, establish correction retention, or compare capacity.

## Actual native path specified by the code

1. A separate `prepare` process creates the real `CognitiveStore` recovery anchor.
2. The example opens `AgentdProductionWriterHost` at that independently retained
   cut and imports the typed document via `remember_with_kg`.
3. It registers the fixed native memory owner, calls actual `codex_hepta_agentd::run`,
   waits for the real embedded App Server, and promotes the controlled fleet state.
4. `AgentdClient` opens the existing Unix control socket. The control handler checks
   lifecycle/readiness and delegates to `AgentdNativeMemoryCell`.
5. `admit_memory_cell` checks live authority/source/key and durably spends the nonce.
6. `NeuronModelPort::execute` checks the exact request tuple and current source,
   starts the fixed fresh Python child, then validates its execution receipt and
   rechecks source/authority after the call.
7. The source owner commits the execution digest. Status delivery reauthorizes the
   source before returning the retained text and complete execution JSON.

This is the existing port boundary. It does not execute `NeuronRuntime.tick`,
create calibrated `SignalReceipt` output, or integrate default production startup.
The explicit qualification feature and controlled authority issuer remain required.

## Controls and source fences

The base and shuffled reads run in separate fresh processes using the same
checkpoint, scope and question. Base generation disables the adapter. Shuffling
permutes the actual adapter tensors with fixed seed 91473 and records admitted
and consumed adapter identities. It cannot save or activate that perturbed state.
Native generation is also fresh-process; there is no third independent repeat of
the native adapter arm and no trained-daemon restart/read demonstration here.

The example requires zero dispatch before wrong-key and wrong-role refusals,
one dispatch after the legitimate result, and still one after replay, authority
withdrawal, source correction and source withdrawal. Forged production claims
are rejected during owner construction. It explicitly checks that a cached result
cannot escape the correction fence. These are meaningful boundary checks.

The authority-withdrawal test toggles a controlled `AtomicBool` and then restores
it; it is not persistent external-authority revocation across restart. Correction
and forget use actual durable source mutations, but the corrected value is not
retrained or decoded. Old-source rejection is the result being tested.
The authority is not a current GitHub ACL verifier or production supervisor grant.

## Parameter measurement and trace completeness

The source supports narrow, attributable measurements: a training receipt with
actual updates and adapter tensors; per-command stdout/stderr/status and elapsed
time; native request/raw output/process bootstrap files; source-owner execution
commit; exact generated/prompt token IDs; and final checkpoint/source hashes.
After a successful run, independently compare all three prompt-token arrays,
training steps/loss/visit counts, native execution digest, control adapter modes,
and before/after pins before describing the three arms as a matched comparison.

The native worker reports model parameter bytes across the loaded model and its
adapter, explicitly excluding allocator overhead. Its process RSS includes more
than parameters. Training separately reports trainable parameter, gradient and
optimizer tensor bytes. These are different quantities and must not be summed
as a complete live peak or treated as equal deployment storage.

The explicit feature forward is measured separately, but `generate()` performs
autoregressive internal forward work that is not counted per token in a forward
ledger. Three decoder queries do not mean three total transformer forwards.
Native `latency_micros` starts after initial metadata inspection and before model
loading; the enclosing command wall includes subprocess startup and earlier work.
The summary does not include a quality-matched complete cost bill, allocation
timeline, all buffers/KV cache, full runtime dependency bytes or OS/network cost.

Runtime identity pins source files, interpreter bytes and selected package versions.
It does not hash every dependency binary or attest a remote machine. The Q24
signals are tanh of selected hidden channels and top next-token probability
values, not calibrated answer correctness, OOD, semantic confidence or a learned
memory-specific head. UTF-8 Q16 padded features bind the query bytes; they are not
a learned semantic encoder.

## Concrete execution risks and shadow compatibility

No additional certain source defect requiring mutation was found in this static
review. The current primary checkout is dirty, so the strict `identity()` guard
would reject a local probe there before model execution; qualification must use
the intended clean committed checkout. This is an expected gate, not a request to
relax it. All input, process and output bounds should remain unchanged.

The example's `claim()` deliberately fills HNMF `objectiveDigest` and
`nduStateDigest` with one fixed qualification profile digest. These must never be
reused as a real objective/NDU provider when adding `NeuronRuntime.tick_shadow`.
The new shadow interface must accept actual context authority or fail closed.

Preserve the v1 worker's closed request schema and
`input_digest == source_binding_digest` contract. A v2 tick path should separately
bind the real full tick semantic digest to source/query identity and retain the
complete model/encoder/head/generation/feature/output-width tuple and source
checks before and after execution. Shadow output must remain distinct from a
calibrated result and deny production actions until separately qualified.

`native_backend.inspect` hashes every `memory_cell_native/*.py` file. Adding a v2
helper changes the runtime pin even when v1 behavior remains compatible. Recreate
configuration pins on the final exact source before qualification; correctly
rejecting an old runtime configuration is not a v1 wire incompatibility.

All conclusions above retain `production_qualified=false`,
`neuron_runtime_calibrated_tick=false` and no scientific performance acceptance.
