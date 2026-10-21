# P24 — prevent finite optimizer-state alias corruption

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.
Exact parent: P23 [#3052](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3052)
at `2ad056359c78765c6ac564cbc88494bf49da8fe9`.
No ancestor, main, model authority or deployment changes.

## Reproduced blocker

P23 isolates trainable Student/Slotizer *Parameter* storage, but P21/P22
optimizer state checks only verify finite values and supported state keys.
A caller can set `SGD.state[p]["momentum_buffer"] = p.detach()`, yielding a
distinct tensor object backed by the **weight itself**. PyTorch 2.10 CPU
reproduction with p=1, gradient=0.5, momentum=0.9 and lr=0.1 produced
**1.26** rather than the isolated-state result **0.86**, with all values
finite; the prior step guards could falsely issue a success receipt.
Two distinct AdamW moment keys can similarly alias physical bytes.

## Scoped changes

- Extend the existing physical-storage isolation check to optimizer states
  as well as trainable weights. Check before a projector, after hooks, and
  after a physical optimizer step through the existing safety gate.
- Reject any overlapping storage among owned weights, momentum buffers,
  AdamW moment and scalar state tensors (conservative shared-allocation rule).
- Validate momentum/moment shape, dtype and device against the owner weight;
  require an AdamW tensor step counter to contain exactly one scalar value.
- Add four synthetic CPU regressions: SGD momentum aliases a weight,
  AdamW moments alias one another, late alias from a projector hook, and
  malformed finite momentum tensor shape.

This is not a model performance benchmark or a production transaction. It
does not protect tensors *outside* the checked optimizer, external I/O,
malicious native extensions, independently attested teacher checkpoints,
future/OOD quality, physical GPU p99/energy or full-size training. The
frozen 421M cognition control, EmbeddingGemma 2 Perception/Memory Stem,
T5Gemma 2 Encoder comparator, native 150M/300M latent Students and
Cell-local Gate/Adapter/Task-Action-Value Heads/Local State/external Memory
remain unchanged.

Require the **exact P24 source SHA** to pass native CPU Stem smoke,
architecture, full blocking-ci (cargo-deny and Windows/Linux/macOS Bazel)
and v8-canary, followed by independent model/data/hardware receipts and
authorization. Queued/skipped/cancelled/stale checks are not PASS.
