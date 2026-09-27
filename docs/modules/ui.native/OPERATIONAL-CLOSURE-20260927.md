# ui.native operational closure: source changes and evidence ledger

Date: 2026-09-27. Candidate: `work/ui-native-operational-closure-20260927`.
Parent: `33fecc526481ab3782429d8d948c8c373244eeab`, from PR #1071
(`work/ui-native-release-hardening-20260927`), continuing #1059 and #1046.
This is an isolated stacked candidate, not a statement that main has these changes.

The exact executed commit/tree must come from a retained workflow receipt, not
from this prose. `CURRENT_SOURCE.json`, `IMPLEMENTATION_MAP.json`, native source
bindings, and the generated inventory remain the identity entry points. No
production, physical-platform, or release claims are promoted by this change.

## Current implementation

1. Refresh invalidates the action-bearing view before authenticated I/O. A
   failed request, malformed digest, invalid generation, or generation regression
   leaves no actionable view. The display revision counter and raw upstream
   generation high-water mark survive the failure; successful recovery cannot
   reuse an old confirmation number. Only a new session resets these counters.
   The UI also drops its binding/revision on refresh failure. Old terminal
   receipts remain readable without a fresh view, but new effects do not.
2. Platform request binding is now `hepta.ui.native.platform-request.v2`.
   The request hash is a JSON tuple of domain, subject, endpoint ID, endpoint
   manifest digest, session ID/generation, operation ID, action, display
   revision, projected view generation, authenticated view-content digest,
   optional resource identity digest, and payload digest. The owner still
   independently issues/signs the complete grant; UI does not mint authority.
   Admission reconstructs this context from its connected runtime. A caller's
   signed intent is retained for duplicate detection, including denied intents.
3. System path confirmation includes canonical path and opened-file identity.
   Unix uses device/inode/mode/size and modification/change times; Windows
   reads volume/file identity from an already-opened handle through the existing
   Windows private-state owner. The app retains `forbid(unsafe_code)` and adds
   no new crate dependency. Immediately before effect entry, the system adapter
   reopens, compares and retains the resource snapshot through invocation.
4. Journal v5 introduces `observation_closed`. This means observation has ended,
   **not** that the effect succeeded, failed or never happened. It contains no
   terminal status/digest. Only `indeterminate` can close; Prepared and Invoking
   cannot be archived. Closed observations are immutable, omitted from automatic
   reconciliation, and can be compacted into the existing durable retirement
   frontier. Reusing that operation identity is then rejected after restart.
5. The history UI distinguishes prepared/not-dispatched, unresolved/may-have-
   executed, observed terminal outcomes and observation-closed/unknown. Its
   closure action does not invoke the platform and has no retry side effect.
   Capacity telemetry exposes active, pending, closed and retired counts. A
   full active set can compact already completed/closed records, never live
   uncertain records, and never discard a retirement identity.
6. Native source/evidence readers use explicit strict UTF-8, independent of a
   Windows console code page. Payload Debug output is redacted.
7. The ordinary installed Linux/Xvfb runner now records raw launch-to-readiness,
   launch-to-visible-window, close duration and process RSS samples bound to the
   package binary digest. It does not claim input-latency, soak, physical-display
   acceptance, or a percentile/budget result from its two samples.

## Migration and crash semantics

V2/V3 legacy journals and valid checksummed V4 journals remain readable. The first
persisted change writes V5. A V4 envelope is not permitted to carry the new closed
phase, even with a recomputed checksum. V4 checksums continue to use the V4 domain;
V5 checksums use V5. The checksum detects corruption, not malicious rollback.

Existing terminal/uncertain intents can be returned/reconciled without new
execution. Old v1 grants do not authorize a fresh v2 operation. A historical
Prepared intent must pass the new admission context and cannot silently migrate
an old grant. No identity rotation or journal deletion is a recovery mechanism.
Rollback binaries must support V5 before a release using V5 is admitted. Downgrade
compatibility is a release gate, not solved by restoring an old operation file.

Durable Prepared still precedes permission; durable Invoking precedes platform
entry. A failed terminal write latches journal health. Restoring storage in the
same process does not lift this fence. Reopen uses the persisted Invoking record
and reconciles without replay. Explicit observation closure never rewrites that
unknown result into a terminal success.

## Evidence and adversarial coverage

Local actual execution: 96 Python tests passed via
`python3 -m unittest discover -s scripts -p 'test_hepta_ui_native_*.py' -v`.
They test source identity, evidence aggregation/inventory, package security and
UTF-8 enforcement. They are **not** Rust build evidence.

New Rust cases cover refresh I/O/digest failures and monotonic recovery, raw
upstream regression after invalidation, read-only terminal duplicates without a
view, all confirmation-context axes, same-byte file replacement, snapshot
stability, closed-unknown restart/retirement/immutability, refusing live archival,
multiple batches across restarts, V4/V5 schema confusion, runtime no-replay after
closure, and effect-return/terminal-write loss followed by restart.

Rust declarations above are not counted as passes. Use the native remote build
logs and exact-head + deterministic-main-merge six-profile receipts for actual
outcomes. Formatting proposals, unsigned packages, inventory matches and skipped
jobs cannot establish qualification.

## Remaining gates (do not erase these by changing terminology)

- **Path-only handoff:** identity comparison detects replacement before the last
  check and retains the original object, but `open`/`explorer`/`xdg-open` still
  consume a path. Another process can change path resolution at the last OS
  handoff on some platforms. A descriptor-consuming OS broker or an enforceable
  namespace pin plus real race tests is needed before claiming full TOCTOU closure.
- **Lifetime capacity:** the existing retirement frontier remains bounded at
  32,768 identities. Closed-unknown compaction fixes active-queue accumulation,
  not unlimited lifetime storage. At the limit the owner fails closed. A durable,
  independently rollback-aware segmented retirement store is still required for
  unbounded service; clearing the frontier is forbidden.
- **Real uncertainty:** SystemPlatformAdapter still has no operation-query API
  for launcher effects. Ending observation is honest operational closure, not
  evidence of what the external application actually did.
- **Installed release:** exact-head/merge qualification, V5-compatible rollback,
  installed macOS/Windows lifecycle, signed/notarized distribution, key rotation
  and revocation custody, physical IME/DPI/screen-reader acceptance remain separate
  gates. No missing signing keys or human acceptance are substituted with fixtures.
- **Performance:** raw installed Linux observations are available only after the
  instrumented runner executes. Input-to-paint latency, saturated-journal
  latency and long-duration resource stability require larger production-shaped
  workloads. No invented measurements or thresholds are supplied.

## Review and integration order

Review the runtime/journal protocol delta and adversarial tests first; verify
strict native builds on the exact candidate next; then verify the deterministic
merge with one pinned main. Source identity maintenance updates only the native
row and its cross-owner source fingerprints. Keep ordinary UI-only development
lightweight; require the above boundary tests for grants, external effects,
persistence, recovery and updates. Independent release admission stays separate.
