# Reader composition regression repair without weakening runtime checks

Date: 2026-10-13. Continuation of PR #1697.
Observed predecessor: `a28ff6baadb9869305ded6d2d24eb06cd36b2651`.
Fixture repair: `a87e56e6cfe6d2286cb8a59cd201e735576427fe`.

## Completed predecessor evidence

Run **38392374259**, job **115294508399**, finished with failure. Its actual
log shows **14 matrix + 54 contract + 29 native + 61 Group + 28 response =
186 tests passing**, then **31 adapter/composition/replay/counter tests,
29 passing and 2 errors**. This is **215 passed of 217 executed**, not a
successful workflow. No tests were skipped inside these six suites. Actual
pretrained acquisition, training, replay and smoke were skipped by the failed
combined test gate. The corrected training counter and all four real-PEFT
counter regressions passed. The nine exact-body preservation regressions also
passed. These are tiny-fixture/source checks, not pretrained capability gains.

Retained failure artifact **11815682386**, reported by GitHub as 96,004 bytes,
33 files, ZIP SHA256
`e03ff5a97b8034f3b1fca631083ed9133af603cfc4adb4bee38d70217f57a3e0`.
This turn did not rehash the archive locally: container and Python probes both
returned infrastructure ClientError. No local execution pass is claimed.

## Why changing the production guards would have been wrong

The disabled-adapter test expected `disable_adapter()` context exit to restore
an immutable inference instance automatically. Pinned PEFT 0.17.1 calls
`enable_adapter_layers()` on exit; `BaseTunerLayer.enable_adapters(True)` calls
`set_adapter`, which enables gradients on the active adapter. The unchanged
production `_check_active` correctly rejects that now-trainable instance.
The test now proves rejection both while disabled and after re-enable. It
constructs and verifies a NEW frozen instance to demonstrate valid recovery.
Verification never silently freezes, switches or heals a mutated resident.
An additional native-owner test verifies that these rejected reuse attempts
produce no new successful observation and do not silently reset gradients.

The distinct-composition test previously loaded tensors from a safetensors
file, changed one tensor, and wrote back into the SAME file before digesting
those loaded tensors. CPU safetensors can use memory-mapped backing. The test
was not a sound construction of an independently owned candidate: overwriting
the backing inode can invalidate the relationship between the in-memory map
and serialized content. The observed failure was a serialized tensor digest
mismatch; the check must not be removed to make the two-owner assertion pass.
The repair clones every tensor into independent storage, writes a NEW inode,
loads it again, verifies every tensor and its digest, and only then replaces
the fixture copy. The original candidate remains byte-identical. It confirms
that two actual different adapters have two different Reader identities and
resident objects, then verifies each resident. A new negative control updates
the file checksum but retains the old tensor receipt and must still fail
before PEFT attachment.

The production adapter loader, source/data selections, optimizer, LoRA profile,
response loss masks, Reader bindings, independent gates and model weights are
UNCHANGED by this repair. All original test names remain, with two additional
regressions. Mutated fixture receipts are test material only and cannot serve
as real training or independent review records.

## Current execution lineage

Run **38421445932** at exact repaired test source `a87e56e6...` was observed
passing the entire required source-test step and original archive acquisition,
then entering the official pretrained Reader response-learning step. At the
creation of this note it was still in progress. This is not yet a completed
training/replay result; subsequent observations must carry that actual run and
source identity, never borrow a prior result or relabel historical development
as independent confirmation. This documentation-only commit does not alter the
runtime used by that already-started run and does not request duplicate fitting.

Primary implementation references:
- https://github.com/huggingface/peft/blob/v0.17.1/src/peft/peft_model.py
- https://github.com/huggingface/peft/blob/v0.17.1/src/peft/tuners/tuners_utils.py
- https://huggingface.co/docs/safetensors/speed

Five independent experiments remain incomplete. A green mechanics suite cannot
qualify semantic sufficiency, response-learning benefit, Group/NDU reasoning,
multimodal transfer, compute matching or production adoption.
