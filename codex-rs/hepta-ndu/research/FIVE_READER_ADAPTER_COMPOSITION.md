# Saved response candidates must become exact Reader compositions

Date: 2026-10-13. Parent: `edbb8975695bdf32a78927ffc2420adc5127b0f5`.
Continuation of PR #1697. No production activation, forced update, independent
approval or claimed natural-task superiority is part of this change.

## Actually verified before this increment

Group run **38387996412**, job **115264430367**, exact source
`e1ccb07f03da831dbd183759c1425a5e165d0180`, completed SUCCESS. Its decoded log
records **14 matrix + 54 five-contract + 29 native + 61 Group tests = 158
passing**, zero skipped, followed by successful Python compilation. The 61
Group cases include the retained 45 and all 16 batching/scalar/partial-cost
regressions. This closes the observed Group source-test failure at that source;
it does not establish natural-task reasoning. The subsequent scoring-only
`edbb897...` did not change those Group/shared-utility bytes.

Retained artifact **11807369453**, GitHub-reported 44,239 bytes / 17 files,
ZIP SHA256 `34c9944ee7d32ba1d182541048efa3cc6c3b61cf618afe2f178d8e84b97f17b4`.
No local rehash is claimed: both container and Python probes still returned
infrastructure ClientError in this turn. The new composition tests below are
SUBMITTED, not locally passed. Historical pretrained reference success remains
separate from current response-learning/composition evidence.

## The missing connection

The existing response learner can save and reload a trained LoRA. The original
NativeSession descriptor and reader_bindings represented only the BASE snapshot,
so a saved candidate could not be registered as a distinct native Reader and
used by the existing Group owner. Silently attaching LoRA while retaining the
old Reader identity would also reuse the wrong qualification and resident key.

The solution is an explicit **hepta.five-native.bundle.v2** Reader descriptor
with `response_adapter`. V1 base-only Reader and Head identities are unchanged;
V1 rejects an adapter field instead of ignoring it. V2 is Reader-only and cannot
omit the composition. It is not a new model owner or generation implementation.

`five_reader_adapter.py` connects the existing training-receipt format to the
existing NativeSession. Its optional PEFT dependency is lazy; the plain Group
source suite remains usable without Transformers/PEFT. All inference still uses
`generate_exact`, the original SYSTEM prompt, tokenizer and decoder contract.

## Exact composition and immutable ownership

The descriptor binds the actual adapter directory inventory (config,
safetensors, optional README), the original base snapshot, original base tensor
digest, saved adapter tensor digest and exact training receipt bytes. Only the
existing rank-4/alpha-8, q_proj/v_proj, no-dropout/no-bias LoRA profile is accepted.
Config options are checked against that explicit profile. Saved metadata paths
or auto_mapping do not load a base or Python class. Pickle, extra files, nested
material, symlinks and over-budget adapter payloads are rejected.

Before publishing an owner, the existing strict loader verifies the original
base. Composition verifies that the ACTUAL loaded base tensors match the
training receipt; PEFT attaches only to this new disposable frozen object. Every
materialized LoRA tensor must equal saved safetensors, all parameters are frozen,
and all layers must have exactly the default adapter enabled, unmerged and
consistent. Failed composition is not published or converted to base-only use.

Reader identity includes BOTH base snapshot and complete response-adapter
identity. The resident key retains scope, purpose, generation, arm and replication
semantics and adds this composition identity. Same-composition Cells may reuse
one owner; different candidates or base-only/composed Readers cannot alias.
This implementation does NOT share a mutable PEFT base across different adapters:
distinct compositions pay for distinct model objects. The intended persistent
unit is a fixed group Reader, not a full Reader adapter per lightweight Cell.

Current files, active adapter, original base tensors and adapter tensors are
rechecked on resident reuse, after generation and at close. Full tensor hashing
has real overhead; total owner wall time includes loading and verification,
separately from generation-only timing. No TCO, energy or speed claim is made.
PEFT generation forwards are counted on get_base_model(), not on a wrapper
whose forward can be bypassed by generate().

The Group owner already delegates Reader calls to NativeSession. It can consume
this new descriptor without another Reader service or per-search-node model.
Its descriptor/bindings and independent admission must be regenerated for the
new Reader identity. A base-only gate or training receipt cannot qualify the
composed Reader. No currently served model is selected by descriptor creation.

## Historical cross-process replay, with costs and original outputs retained

`five_reader_adapter_trial.py` is added AFTER the existing response study in its
workflow. It reuses already-staged original weights and actual saved adapters.
It chooses one historical question by identity hash and the fixed no-evidence
and oracle-plus-distractors conditions BEFORE reading prior answers. Unavailable
oracle conditions stay unavailable, without replacement. Both aligned and
shuffled candidates are reloaded through NativeSession in new owners; at most
four actual replay calls are made, paid as ADDITIONAL work, not new tasks.

New raw answers seal before comparison with the previous sealed raw answers.
The check requires exact original answer, input-token hash and output-token hash
for comparable successes, not a semantic score. Any execution/close/mismatch
failure is retained and exits nonzero; no hidden retraining, best-answer selection
or new human-sufficient stamp occurs. This replay has been WIRED, NOT observed
completed at publication. Source samples remain historical and previously exposed.

## Tests and use

The new modules define 22 composition tests and 5 replay-planning tests. They
reuse the existing tiny random Llama fixtures and actually request PEFT fitting,
reload, logits comparison and generation in the tests. Their weights are NOT
pretrained evidence. Coverage includes exact composition, unchanged base binding,
old-identity denial, same/different-owner behavior, scope/replica isolation,
resident byte/tensor tampering, disabled adapters, immutable bases, capacity,
pickle/symlink rejection and inability to replace independent review.
All inherited suites remain required before any historical model execution.

To assemble an unadopted candidate after copying its actual adapter and original
training receipt under an approved material root:

```sh
python scripts/memory_cell/five_reader_adapter.py \
  --root /approved/materials \
  --base-descriptor-sha256 <existing-base-descriptor-sha256> \
  --adapter-path candidates/reader/adapter \
  --training-receipt-path candidates/reader/training-receipt.json
```

The command writes exact canonical bytes to `bundles/<sha256>.json` and refuses
an existing destination. It does not load a model, create signatures, update
CURRENT or grant a task capability. Approval and future evaluation still belong
to the original independent Reader/five-experiment flow.

Primary PEFT API/format references:
- https://huggingface.co/docs/peft/v0.17.0/package_reference/peft_model
- https://huggingface.co/docs/peft/v0.17.0/developer_guides/checkpoint

The five requested independent experiments remain incomplete. This increment
connects trained checkpoint bytes to the existing execution owner rather than
claiming a learned improvement from an unexecuted path.
