# P5 exact source-HEAD and merge-candidate executable conformance

**Research / DENY_ALL / NO_MODEL_SELECTION / NO_RELEASE.**

An additive child of [P5 original source-group pairing #2290](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2290), frozen starting SHA `204e1d1bc9144bdc329c2eeac0501b52fc97bb98`. The original 64/256/1024/4096 experimental designs, original model/score claims, Python source, source-group pairing rules and actual data authority remain unchanged.

## Specific gap closed

The prior workflow used `ref: ${{ github.sha }}` for pull_request events. On GitHub, that is the prospective synthetic merge commit, **not necessarily the exact authored research branch HEAD**. A passing merge worktree could not independently show that exact source-head logic was executed. The updated workflow uses an event-scoped `source_head` / `synthetic_merge` matrix on PRs. On push it runs one `source_head` profile only. Each profile checks `git rev-parse HEAD` against the exact GitHub event SHA before compilation or testing; there is no fallback to another branch/HEAD.

Both profiles execute the **genuine original** P5 parent `scaling_frontier` and child `p5_cluster_replay` source and original tests, including missing fourth scale = hard denial. Full git worktree identity and SHA-256 of the four actual Python files are saved. Shell uses `set -euo pipefail` and both normal/optimized test logs are uploaded independently (including failures); no success is claimed from queued or skipped jobs. Permissions stay `contents: read`; checkout has `persist-credentials: false` and the artifact is not a model, teacher, human-label, or production certificate.

## What was **actually** independently executed before this PR

The four exact GitHub original-source research blobs were reconstructed in the local container and their `git hash-object` was checked byte-for-byte against the current original PR #2290:

| Original registered path | Git blob SHA-1 |
| --- | --- |
| `scaling_frontier.py` | `8f6fd6ff3465646088ca930933412d5b5a671596` |
| `test_scaling_frontier.py` | `dfe318c9848db743eaec1052aa49f1bee71846ed` |
| `p5_cluster_replay.py` | `daec2d655bd04ce842b5bbf240e833150c640226` |
| `test_p5_cluster_replay.py` | `caa237d7ec81f476c957cf31f390f19fb2586c80` |

Executed **23/23 normal** and **23/23 `python -O`** unittests, zero failure and zero skips on the four exact current parent+child module sources. Unlike the earlier local P5 report, **no stub `scaling_frontier` was used**. This closes only the local full-code integration question, **not** GitHub-runner completion, original-source/label-issuer authentication, new pretrained forwards, prospectively independent task scores, whole-lifecycle model energy or 10T/100T equivalence.

## CI qualification gates

1. Source HEAD and synthetic merge each must complete with the expected SHA and all required tests. A push is source-head-only and never substitutes for an actual PR merge review.
2. Require fully physically observed and independently scored four-level original-source-aligned rows, not synthetic test fixtures, for a **future** genuine scaling efficacy claim.
3. Existing `DENY_ALL`, `production_accepted=false`, no extra signed FINAL-use, no main merge and no selected model remain in force.

Full unittests are fast and source-only. The new CI matrix doubles on a PR by design to separate evidence, not to simulate multiple physical test environments. Even green dual CI grants no model/Cell Split/NDU runtime authority.
