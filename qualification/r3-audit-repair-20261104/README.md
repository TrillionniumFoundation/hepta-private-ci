# Original r3 product contract repairs — 2026-11-04

This candidate starts from `907d4f512819a71bece82e7f89944e9406466e36`
(tree `36692b4e9c18e1c06e5efc5a8e6ba6b22980cdce`). It repairs six
specific source/fixture problems observed in the original blocking CI,
without changing its test set, timeouts, retries, ignored cases or gates.

## Repairs

1. Restore `CwdRelativeTurnDiffs` when selecting the per-environment display root.
   With the feature disabled, the Git-root/fallback behavior is unchanged. This
   exact source file is already present in `5d19a578ac28a6ce7fc67a348b10297dc370c19f`;
   the rest of that divergent branch is not imported.
2. Resolve the Agentd executable through the existing Cargo/Bazel runfiles helper
   before embedding its absolute path in the five-Agent release wrapper.
3. Read cognitive KG evidence from the actual `revision_facts_v1` storage
   representation. Reconstruct the complete current generation from each
   memory's latest published revision, count active verified occurrences, and
   retain the independent source, fact-set, digest, count and physical-send
   assertions. Legacy `kg_nodes`/`kg_edges` copies are not populated by this
   representation.
4. Canonicalize the trusted temporary AuthBus replay checkpoint parent.
5. Canonicalize the two trusted kernel-evidence recovery fixture parents.
6. Canonicalize the temporary terminal-cell fleet root.

The last three repairs let positive macOS fixtures reach the intended assertions
despite the system `/var` alias. Production path validation and all negative
authorization/recovery tests are unchanged.

## Query validation

From the repository root, with Python 3:

```sh
python3 qualification/r3-audit-repair-20261104/verify_cognitive_projection_sql.py \
  --repository . \
  --output /tmp/hepta-cognitive-sql-result.json
```

The script extracts the actual SQL from the candidate Rust source and compares it
with the fixed r3 source using an independent SQLite generation-history oracle.
The fixed r3 commit must be present locally; a shallow checkout can instead pass
its exact file with `--baseline-file PATH`.

The ten cases cover initial publication, scope isolation, multiple memories,
correction, tombstones, unverified facts, an empty generation, a later active
generation, missing immutable facts, and unsupported storage modes. The retained
result records query-level evidence only. Independent review additionally checked
future receipts, future triggers, a concurrent scope, unpublished facts and a
missing storage witness; all five cases passed.

## Original execution still required

The candidate must run the existing Linux GNU/musl, macOS and Windows CI. The
original cognitive process case is
`real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends`.
The original cwd regression contains seven cases: five enabled originators and
two disabled controls.

The pre-repair r3 run
[41797888123](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41797888123)
completed with 24 successful jobs, 9 failed jobs and 4 skipped jobs. The nine
include two failing aggregate jobs; these are not nine independent defects.

`just fmt` and `git diff --check` passed on the combined source. Query validation
and source integrity do not qualify the complete Agentd process or a release.
Other Core/App Server/WebSocket/Windows failures, external provider capacity,
trusted production composition and the research benefit gates remain open.

## Second repair batch

The follow-up is based on the first published repair commit
`e729e6c2becb528e3a6b49c9e5bbea57bd26637a`. Its production changes cover
Hook metadata, bounded private attempted-call observations, terminalization
admission, request-scoped WebSocket identity, ordered realtime handoffs and
retained Unix shutdown signal subscriptions. Fixture changes repair the actual
handshake, execution readiness, lease, queue and resume preconditions. Windows
helper layout and bounded test-only observations preserve the original strict
permission assertions.

See [SECOND_BATCH_QUALIFICATION.md](SECOND_BATCH_QUALIFICATION.md) and
`second-batch-qualification.json` for the 25 actual native validation phases,
their complete JUnit identities, preserved failures, exact source trees and
platform limits. `second-batch-generation-receipt.json` binds those generated
documents. The accompanying final composed-source manifest and native-check
receipt distinguish the source used for scoped formatting/lint checks from
the separate earlier test trees. The final GitHub commit and full publication
tree are recorded in the PR after publication.

The two helper lock-generation runs remain separate. The first covers 805
inputs; the combined Exec Server and CLI run covers 806 inputs and succeeds
with the original update/check commands. Both generated locks are byte-identical
to the existing lock. Their `windows-helper-*` receipts retain the fixed source
identities and do not grant product or Windows execution qualification.

The final original platform matrix remains the acceptance gate. In particular,
the original Windows security failures, Windows Code Mode timing and Intel PTY
drain cause are not closed by Linux passes or by added diagnostic output.
