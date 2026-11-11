# MEM8 original-owner integration checkpoint

**Status: HOLD / NoUpdate. Native owner validation is pending.**
Checkpoint: 2026-11-11 01:36:54 UTC. New real actor episodes: **0**.

## Confirmed progress

[Common source #5873](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5873)
is commit `96038ccf0660154fac143ba6cbe4be81e00813e8`, tree
`1277666f3285cdf006d36478e6f74ddec38e1fe0`. Its two hosted MEM jobs passed
nine groups: **154 execution observations, 120 distinct test IDs, 34 repeated
observations, zero failures and zero skips**. The 14-case revocation campaign
uses no model calls. The original downloaded artifacts, logs and independent
binding audit are retained in [evidence #5889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5889).

macOS Agentd and TUI targets also passed. Later Windows results still contain a
durable signed-credit fixture failure. These results do not establish a whole
repository CI pass or complete cross-platform owner qualification. A separate one-line Windows fixture repair
is published in [#5895](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5895);
its native result and possible later lock-sharing failure are still pending.

The three memory layers, matched interventions, strong baselines and unchanged
source-group adoption thresholds remain defined by the
[MEM6 protocol](../../memory-cell-mem6/PROTOCOL.md). The
[ordinary-product contract](../../memory-cell-mem7/PRODUCT_MEMORY_CONTRACT.md)
continues to govern actual fresh-session inference and persistence-off.

## Implementation and review boundaries

The source-admission stage is [#5888](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5888).
Its current commit is `1b86d19810c9d422a8f8ea3b76a0a2e8c9956585`.
Five dependent commits are published in
[draft integration validation #5892](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5892);
the final source is `eb430c1e4f122784f5a91d4a5ddf2ae8bb5063da`,
tree `24bea5bc952f3bab7f9180ce7b340e22794e63ad`.
See `STAGES.json` for exact file preimages/postimages and expected case IDs,
and `BLOCKERS.json` for each published commit and the outstanding conditions.

| Stage | Implemented boundary | Native result |
| --- | --- | --- |
| A | Strict complete-snapshot parsing, typed original source observations, explicit Verified/Provisional status and retained source revalidation | Exact formatter postimages applied; tests pending |
| B | Original-writer atomic canonical import, durable source/revision mapping, original receipt reconciliation and explicit commit/rollback settlement | Pending |
| C | Update, withdrawal, source/owner revocation, foreign head changes, Unicode and Provisional retrieval regressions | Pending |
| D1 | Bounded typed control/client/host interface; actual UDS refusal without configured source ingress | Pending |
| D2 | Configured original writer/source/namespace; retained cancelled work, bounded pending admission and unresolved-owner readiness fencing | Pending |
| D3 | Actual App Server/AutomationStore drain with commit, revoke and panic cases, including two cancelled queued imports | Pending |

Each B–D3 stage has a separate commit and branch. The temporary aggregate
validation comparison lets the native job retain the complete formatter output
before the review bases are split at those existing boundaries.

The control caller supplies only snapshot JSON. The embedding supplies the
original writer, private scope, namespace and source verifier. Hashes and
provenance strings do not authenticate a source; authentic custody does not
automatically make its facts Verified. No authority constructor or deployment
binding is synthesized by this checkpoint.

Canonical mutations, the source/revision mapping and the full import receipt
share one SQLite transaction. An identical retry returns the original receipt
without adding another canonical memory revision. Coordination and checkpoint
bookkeeping are not claimed to perform no writes.

Retained work survives cancellation of its response future. Drain waits for an
acknowledged commit or rollback. Unresolved settlement is published before the
pending count is released. The original writer's shared import mutex keeps
queued episodic transactions behind its existing native commit fence; readiness
and ordinary cognitive reads also observe unresolved state. Existing fenced
owner recovery observation is preserved.

SQLite can release a lock before a failed commit acknowledgement is observed.
The new mutex protects later episodic imports; ordinary native writes before
that observation retain the existing native transaction contract. The final
source check is a read linearization point, not an external-effect lease.

The v1 bridge admits at most 32 lifetime fact slots. A retired slot stays retired,
including when Python explicitly writes a valid newer version. This is narrower
than Python's write-after-revoke semantics and requires a separately authorized
namespace or a future qualified reconstruction path. The control input is
bounded at 20 KiB; the native snapshot parser is bounded at 64 KiB.

## Actual formatter evidence

The first A job, [130244877806](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42935621920/job/130244877806),
used Rust 1.96.0 and exact source `e68a2fbcc8b72d9081e1cc44ab1066837e53649c`.
The formatter exited zero, changed exactly five A files, and the clean-source
gate correctly exited one. All native test and fix steps were skipped.

The original artifact's before archive matches the published blobs byte for
byte. Applying its complete patch reproduces every formatter postimage. Those
exact postimages are committed in the current A source. No compilation or test
result is inferred from applying formatting. The new source-head run reports a successful format step and is running the
native test command; final receipts and test counts are pending. The full B–D3
integration run is separately queued.

## Runtime and outstanding acceptance

The h remote execution channel currently returns `MCP -32603 Internal error`
for read-only health checks. Earlier native/preflight requests without a
terminal receipt remain **UNKNOWN**. Their original request/session identities
are retained in the runtime archive; no replacement identity was used to replay
them. The MEM6 archive publisher is prepared but has not run.

The restored MEM6 archive remains a verified file-restoration milestone:
61,412,948 original archive bytes and 10,365 restored logical files. It does not
recover original live grants, provider bindings, independent source custody or
external-effect state. Full archive publication is still incomplete.

Historical scientific results are unchanged: fixed-public working-state
retention was 30/84 versus 28/84, with source-level one-sided 95% bootstrap lower
bound **0.0**. The new-source selector comparison was 21/54 versus 13/54, with
9 wins, 44 ties and 1 loss. Their original no-op and bypass accounting stays in
the previous reports. No unseen episodic successor experiment has been run here.

All original open blocker IDs remain in `BLOCKERS.json`. Production source and
provider binding, true memory-off exposure control, matched unseen successor
benefit, strong-baseline/association comparison, deletion and external-effect
qualification, independent full-owner recovery and complete cost/slow
consolidation still require their own evidence. The adoption decision is
**HOLD / NoUpdate**.
