# P22 — roll back nonfinite offline Student/Slotizer optimizer updates

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Child of P21
[#3042](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3042)
at frozen parent `53cbc9beace71a1da8f904eea041357b5b82aaa6`.
No parent, main, Cell authority, CAS/CNS, FinalUse or deployment changes.

## Reproduced blocker

P20/P21 reject malformed owner configuration, nonfinite backward gradients
and poisoned **existing** optimizer state. They did not check the actual
optimizer update. A finite `-3e38` gradient with `SGD(lr=1)` and a finite
`3e38` parameter overflows the parameter to Inf. AdamW can produce infinite
second moments from finite gradients while returning finite parameters.
Both outcomes previously returned a successful local training receipt.

## Scoped implementation

- Before the stock optimizer step, require supported finite dense
  Student/Slotizer weights and reject instance monkey-patched optimizer
  `step` methods or registered step, state-dict and load-state-dict hooks.
- Snapshot *all* optimizer-owned parameter bytes and a deep copy of the
  optimizer state/groups immediately before the physical step.
- After the actual `SGD` or `AdamW` step, check parameter identity, finite
  updated parameters, finite optimizer state and unchanged group settings.
- If any check fails or the stock step raises an exception, restore all
  captured parameter tensors and load the exact pre-step optimizer state,
  then fail closed without a success receipt.
- Regression coverage physically reproduces both overflow classes,
  including existing momentum/state restoration; existing positive SGD
  and AdamW update tests remain in the same CPU smoke job.

## Limits and retained gates

Rollback is **only a scoped pre-step parameter/optimizer-state safeguard**.
It cannot roll back external IO, forward/backward hook side effects,
untrusted producer source bytes, unrelated mutable buffers, arbitrary
monkey-patched modules, optimizer state outside PyTorch, GPU hardware
faults or crashes between write and rollback. The snapshot may consume
substantial extra memory for a 150M/300M student; production-scale
training needs separate transactional checkpoints and storage budgets.

The 421M cognition control, EmbeddingGemma 2 perception/Memory candidate,
T5Gemma 2 Encoder comparator, Hepta 150M/300M latent Student, per-Cell
lightweight heads and external Memory remain unchanged. There is no
pretrained teacher weight download, completed model-scale bake-off,
independent teacher checkpoint qualification, System2/NDU promotion,
Memory write, or activation in this PR.

Qualification requires exact P22 SHA source, successful CPU shadow workflow,
architecture convergence, `blocking-ci` (including cargo-deny and native
Windows/Linux/macOS Bazel) and `v8-canary`; queued, skipped, failed or
superseded commit statuses do not count as PASS.
