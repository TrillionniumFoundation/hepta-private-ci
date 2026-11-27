# Expired registry attempt fixture

Windows main shard 2 at b9 ran three qualification cases: two passed and
`qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`
failed during `lease.admit`, before its expiry/quarantine assertions.

- Run: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45585341998>
- Job: `139107875542`.
- Original log: 689,640 bytes, SHA-256
  `872a48b2467baa6f45ff5b9402fdb54068b85819bf8774eee142f31496ce0236`.
- Observed error: `StaleFence("local lease has expired")` at the seed's
  `admit local intent` step.
- Source: `b9afe1f469ad12c5cd520af0ecef4c8e22f295ed`; the actual merge
  `276d0c1425f266bc2ad8b6024a0468ff58e2384d` has the identical full tree.

The fixture originally set `floor(SystemTime::now()) + 1 second`, then
performed registry reservation, lease inspection/reopen, compact executor
setup and several real H7 transactions. The active-lease interval could
end before those setup writes. Production correctly rejected the expired
write. The subsequent fixed two-second sleep was never reached in the
observed failure.

The candidate changes this synthetic setup lifetime from **one to ten
seconds**, explicitly. After all H7 writes it requires the real
`verify_current` check and an Active persisted head. It then waits for that
persisted head's actual deadline, verifies elapsed wall time, and requires
the exact expired-lease error from `verify_current`. All original
quarantine and ExpiredActive assertions remain, with an additional complete
lease-inspection equality check: only its time-derived disposition changes.

The production expiry rule, persisted hash/fence rules, nextest timeout and
retry policy are unchanged. No SQL is rewritten, no mock clock is installed,
no failed setup is retried, and no expired lease gains write authority.
A setup exceeding the explicit ten-second fixture interval still fails.

At source preparation `just fmt` and `git diff --check` passed. Actual Rust
execution and Windows qualification of this candidate are pending. The
original b9 failure remains a failure; this is not an unchanged-TTL claim.
