# MEM12 provider inputs and recovered MEM11 generation

**122 composed software controls passed. Four contradictory successful replays now fail closed without another execution. Scientific acceptance remains HOLD.**

## Exact model inputs

The offline worker retains the rendered chat prompt and every tokenizer input tensor immediately before `model.generate`. A successful terminal must contain one complete canonical input record bound to the original request and generated result. The parent retains its exact bytes in `model-input.json`; readback checks the file against the original complete log. This records the generation entry inputs, not every internal neural forward step.

The worker source is now a separately pinned dependency. The retained model, runtime, request, worker and source identities remain explicit. No authenticated production observer or original Owner authority is created.

## Reproduced replay defect

The independent reviewer changed four retained successful records while keeping their log hashes consistent: nonempty private state, namespaces equal to the host, changed runtime after execution, and changed loaded source. All four were previously accepted as RETURNED. The shared return/readback verifier now rejects all four, and the same original counterexample script independently confirmed no second execution. These are fixture attacks with zero real model calls.

## Validation and formatting

Clean local source `83e88f62205bf60da5f631d41677355c9ead99e2`, tree `2bfe5efbef91c6a9a005766698bed5dd613f516a`, passed 122 controls with no failures or skips in 30.138 seconds of supervised wall time. An earlier wrapper admission lacked the required source identity and was rejected before any test; that original is retained. Earlier focused runs overlap and are not added to 122.

Repository `just fmt --base 2cc455df8f` completed successfully. All three Python ASTs were unchanged. Ruff and `git diff --check` passed. Tests were not repeated after this final formatting. The formatted source tree is `facd1b8698ff03b05d21de42e515cd151e3ca19f`, published as `69bf5c1fea699b74bc91d5f24604a479b2f61638`. New-head required CI and real-model execution remain separate qualifications.

## Historical operation recovery

Read-only ai395 observations recovered the original `mem11-first-local-generation-20261112-21bb-v3` result, its isolated actor and complete request/journal files. The original generation returned `Hello!` with token IDs `[19556, 17, 2]`, exit zero, no timeout and six namespaces different from the host. Twenty-six independent byte/binding checks passed. This changes the original generation outcome from unavailable to observed RETURNED without replaying it.

This was one historical greeting diagnostic, not a memory-benefit episode. Its provider and handoff source bytes differ from #6136 and this candidate. The original outer runtime job identity remains UNKNOWN. No prior success is transferred to a new source or production Owner. New real-model executions in this recovery: zero.

## Native composition and CI

[#6142](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6142) composes native withdrawal and explicit delivery with MEM11. It also adds seven exact infer-worker-host test names to staged native CI. Its Codespell job [131012707569](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43167505556/job/131012707569) passed after the single encoded-evidence exclusion; the original failure is retained. Other native, strict isolation and repository checks retain their own statuses.

The [evidence manifest](./EVIDENCE.json) and [complete archive](./validation.tar.xz) retain original failures, final logs, command receipts, tested/formatted postimages, independent review and original v3 recovery bytes. The archive was reopened and every indexed member verified. No merge, deployment, weight update or causal memory-benefit acceptance is implied.
