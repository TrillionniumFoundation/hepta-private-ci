# Original Final-use revocation capacity consistency (2026-10-15)

**Base:** protected `main` at `78fdb0cf8537e3a84fc6e0a849707559c80881e8`.
This independent repair does not depend on the P2e/P2f Codex research stack
and does not change the exact original signed final-use verification APIs.

## Observed and reproduced source defect

In the original `codex-rs/hepta-contracts/src/final_use.rs`, the trusted
`FinalUseAuthority::capacity()` snapshot reports
`max_revocations: MAX_CLAIMS` (1,048,576). But the **same original owner**
limits `FinalUseRevocations::revoked_grant_ids` to
`MAX_REVOKED_GRANTS` (16,384) in `valid_head()`, which is called at
revocation-head admission. Consequently `remaining_revocations()` and
`rollover_required_with_reserve()` can understate operational pressure by
a factor of 64 and give misleading reserve alarms.

## Narrow fix

Set only the observational `max_revocations` member to
`MAX_REVOKED_GRANTS`. Add a test using the original authority fixture to
verify the snapshot matches the hard enforced bound, that one remaining
slot triggers a reserve-1 alert, a full registry triggers reserve-0 alert,
and original `valid_head()` admits exactly 16,384 but rejects 16,385
distinct valid grant identifiers.

No schema, signer/trust, issuer-key rotation, revocation-feed policy, nonce
claim, Final-use verification, external provider, module ownership, Cargo
dependency or production effect is changed. This fixes monitoring honesty,
**not** an authorization bypass, and does not qualify Codex physical dispatch.

## Qualification

A separate read-only exact source-head/prospective-base-merge workflow runs
pinned Rustfmt, locked original Contracts checks and final-use tests, strict
Clippy, original lockfile integrity, and clean-source verification. No
new native CI success is claimed until it has actually completed. Existing
global `blocking-ci`, architecture checks and issuer/operator/host gates
remain required. No advisory ignores, skipped security checks or permissions
are introduced.

**No production deployment or broad CI-green assertion follows from this
one source correction.**
