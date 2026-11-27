# Native source-bound memory development

This opt-in development path connects the existing HNMF event, durable cognitive
source owner, Agentd runtime and control socket, `NeuronModelPort`, and a fresh
CPU model process. It does not activate research checkpoints in the default
daemon. Construction is gated by `qualification-cognitive-write`.

## Admission and actual execution

The host imports a typed source document through the recovered
`AgentdProductionWriterHost`. The source owner checks the actual current memory
revision, source-ledger bytes, immutable production intent/commit journal and
outbox, canonical HNMF event, scope, typed role/key, deadline, and live authority.
A self-consistent receipt supplied by a caller cannot replace those journal
records. Each invocation spends its nonce durably before backend entry. Source
and authority are checked again before and after model execution and before the
terminal source-owner commit. Completed responses are rechecked at delivery.

The read RPC accepts only an invocation ID, semantic/procedural role, entity,
relation, and deadline. The server derives the question and prompt. A query
cannot provide a checkpoint, source claim, raw prompt, control arm, model pins,
or expected answer. The initial qualification profile admits a checkpoint with
exactly one training source root, matching the current imported source bytes.
It does not silently admit a multi-source adapter after checking one source.

The native port checks the complete existing `NeuronModelRequestV1` tuple. Its
UTF-8 query features are a fixed binding representation, not a learned semantic
encoder. The worker loads actual retained base/adapter bytes, verifies tokenizer
and ChatML prompt tokens, performs a feature forward and raw autoregressive
generation, and returns measured pins, tokens, values and costs. Hidden-state
and next-token observations are not calibrated correctness scores. This path
does not perform or claim a calibrated `NeuronRuntime.tick`.

Execution receipts are trusted local measurements, not remote attestation.
Source-owner journal commits bind the execution digest. Full bounded
request/stdout/stderr/process receipts are retained separately, and successful
RPC results include the execution JSON. The subprocess timeout includes stdin
delivery. Linux children use the existing parent-death launcher and are also
cancelled when the actual daemon owner exits. Other platforms do not receive a
Linux-equivalent parent-death claim. Filesystem evidence retention does not
claim power-loss durability. Failed or interrupted nonces remain spent; a
restarted daemon reports an unavailable historical job as indeterminate.

## Fixed historical input and limits

`fixtures/source-inputs.tar.gz` contains 29 original files from the retained
domain-development-003 package, including actual GitHub API/log responses,
producer data and evidence. It contains no model checkpoint. Its manifest pins
every member and the original package hash. The selected already exposed case
is `covariance-diagnostics`, failed run `39940937789`, fix
`455e16648ce7069400f5a8e679e4fd0c1a1da613`, successful run `39941261138`.
The producer dataset SHA is
`1642fc42e890f25e32fc5b66289cf07ee3bcf6a81fb4636fd2c2c9333ee74875`.

The native key derives from the original complete symptom, procedural role and
`repair` relation. `source_mapping.json` preserves original source ID, commit,
tree, source digest and actual fetch-receipt paths; the exact derived typed JSON
hash becomes the single native training source root. The daemon example uses
an explicit controlled qualification issuer to import these bytes into the
real owner. It does not authenticate current GitHub permissions or obtain a
production supervisor grant. Correction/withdrawal inputs are controlled fence
tests and are not presented as newly observed CI facts.

The preregistered development budget is a fresh rank-8 adapter, seed 24031,
96 completion-CE updates at learning rate 0.01, one question template, one native
adapter decoder query plus one native feature forward, and separate fresh
base/shuffled decoder queries. There are three decoder queries in total. All
raw outputs and actual training/read costs are retained. The single-case exact
accuracy is an observation without a positive performance gate. This is not
unseen-data confirmation, general-memory validation, or production qualification.

## Independent hosted execution

`.github/workflows/hepta-native-memory.yml` checks out the exact candidate HEAD,
runs scoped `just test`, builds the actual daemon example, and runs the fixed
protocol. The example calls the existing `codex_hepta_agentd::run`, waits for its
real App Server readiness, promotes the controlled fleet generation, and reads
through the existing UDS client. It checks wrong key/role, forged source,
replayed nonce, revoked authority, correction and source withdrawal without
additional backend dispatch. Source-module tests separately exercise durable
reopen/replay, concurrent duplicate admission, and source authorization.

The driver requires explicit portable paths and a clean committed checkout:

```sh
python -I -B scripts/memory_cell_native/native_ci.py \
  --repo /path/to/repo \
  --binary /path/to/target/debug/examples/native_memory_daemon \
  --out /path/to/new-evidence-directory \
  --model-out /path/to/new-base-directory \
  --expected-head FULL_COMMIT_SHA
```

It downloads six SHA- and size-pinned files from public
`HuggingFaceTB/SmolLM2-135M-Instruct` revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`. The download receipt, executed source
archive, exact source inventory, independently retained recovery cut, newly
trained checkpoint, SQLite owner files, raw model/process receipts, controls,
costs and any failure are artifacts. Calls are not automatically retried.

After successful tests and probe, CI runs scoped `just fix` and final `just fmt`
and uploads their patch. No tests run after those modifications in that job.
The recorded source and results belong to the pre-format candidate. Applying a
nonempty patch requires a separate new exact-HEAD qualification; the old result
does not certify the modified source. CI never commits or pushes the patch.

## Opt-in uncalibrated shadow owner

With `qualification-cognitive-write`, an already registered
`AgentdNativeMemoryCell` can create an `AgentdNativeMemoryShadowOwner` through
`shadow_owner`. The host must supply an actual live context authority, a sparse
profile and two independently retained file handles. The context authority must
provide the current subject, objective, NDU snapshot, optional body/modulator,
and a monotonic clock consistent with the journal. No provider is invented when
that authority is unavailable. The historical example's controlled objective/NDU
hashes are not a production provider.

`NeuronRuntime::tick_shadow` shares the ordinary journal/independent-witness
transaction. It uses an explicit profile with no calibration, ECE, false-acceptance
or OOD claim. Its separate observation type always abstains and denies effects;
it has no conversion to a calibrated signal or canonical published checkpoint.
The calibrated `tick` entry rejects a shadow profile before model dispatch.

The v2 worker request preserves the admitted model tuple and binds the complete
`NeuronTickInputV1` digest alongside the original source and query digests. The
Python worker independently recomputes the Rust canonical tick encoding and the
source/query/tick join. The v1 source-bound request remains supported unchanged.
New helper source is included in the runtime inventory, so model registration
must be regenerated for the exact executing source head.

The witness header durably binds owner, logical cell, subject, source cut and
model/profile identity before recovery. A changed source/profile cannot reopen
that witness as another cell; a missing witness cannot bootstrap an existing
journal. The files must remain private to the owner on a lock-capable filesystem.
This boundary does not attest a physical machine or protect against an adversary
rolling back the journal and its independently trusted witness together.

A failed witness acknowledgement retains the original admission, input, model
port and completed raw output for the same-query reconciliation. It spends no
new nonce and invokes no second model. Other incomplete operations close the
runtime for explicit recovery. SQLite completion and sparse-journal commit are
not one atomic transaction. Completed output is immutable through this API and
bound to its original owner namespace. Source/context checks run again after
asynchronous handoff; late authority withdrawal or a durable source tombstone
refuses delivery and closes the owner. Capacity remains held through delivery.

The hosted job adds the affected neuron crate, source/journal/delivery regressions,
stdlib wire checks and actual Rust-to-Python serialization tests. These controlled
fixtures do not execute a pretrained model. The original fixed 96-update v1
Agentd probe remains separate. An actual v2 model-through-shadow qualification,
a concrete production context provider, daemon startup/inference-control wiring,
and calibration/promotion remain independent acceptance gates.
