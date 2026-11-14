# P28 — enforce stock offline optimizer custody in five-split Student rehearsal

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Research-only; no model or production promotion.

## Original reproduced gap

The P27 guard on `multimodal_bridge.shadow_distill_step` did **not** cover the
independent five-split `offline_shard_distill.run_offline_distillation` entrypoint.
That path checked parameter object IDs, then directly called a caller-provided
`optimizer.zero_grad()` / `optimizer.step()`. A subclass or instance-patched
step could write to a foreign Cell, while a process-global optimizer step hook
could mutate foreign state even with fully correct `param_groups`. Distinct
student/readout Parameter IDs could also alias the same physical storage. A
finite output-only check is not a cross-Cell custody guarantee.

## Scoped change

Base: P27 [#3068](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3068)
exact source `a6cc400c8b979c85fca8304c5f4df6b051bc5432`.
Parent #3068 and `main` are unchanged. No new runtime authority or per-Cell
backbone introduced. 

- Reuse the P27 stock SGD/AdamW optimizer lifecycle, global-hook, physical
  storage, momentum/state safety, finite Student-gradient and rollback guards.
- Reject unsafe optimizer ownership before reading any split/evaluation and
  recheck before every `zero_grad`, after every forward/backward hook and before
  each physical training step. Recheck exact parameter ID order and state.
- Replace the formerly accepted instance-step monkeypatches in three original
  proof-of-custody tests with Student forward-hook caller mutations. The tests
  still demonstrate that immutable five-split byte snapshots define reported
  evaluations, without accepting a replaced optimizer lifecycle.
- Add real CPU regressions: hostile SGD subclass, overridden instance step,
  process-global step hook, late registration, overlapping Student/Readout
  storage, and momentum-state aliasing.

The shared guard does not sandbox arbitrary Student/Readout Python hooks, native
extensions, asynchronous writes, or model sources. It makes no claim about
performance of the real 421M/EmbeddingGemma 2/T5Gemma 2/native 150M/300M
candidates, teacher checkpoint licensing, or original-source provenance.

## Current architecture and blockers

Maintain immutable 421M cognition control; EmbeddingGemma 2 shared
Perception/Memory Stem; T5Gemma 2 context Encoder comparator; native Hepta
150M/300M latent Student; per-Cell Gate/light Adapter/Task-Action-Value Heads,
Local State and evidence-ledger external Memory. Training remains offline;
NDU/System2/CellSplit/FinalUse remain non-authorizing.

**Still required:** fresh exact-head Stem smoke, Python lint/format, architecture
source/base/required, blocking-ci, cargo-deny, Linux/macOS/Windows native/Bazel,
V8; independent teacher/data signatures, genuine heldout/OOD/negative transfer,
physical GPU fan-out at N=1/64/128/512/4096 including p95/p99 memory/energy,
model rollback and independent governance. Inherited, queued, skipped, stale or
cancelled jobs are NOT successful checks; no production activation.
