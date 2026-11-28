# Remaining terminal controls: prospective fixture correction

The original e333 native command reached its 240-second deadline with 19 named
PASS records, three FAIL records and six controls without terminal results.
Its complete gate remains NOT_QUALIFIED. The original log and wrapper remain
unchanged; the wrapper's zero summary count is not rewritten into 19 or 28.
The raw-log SHA256 and the exact nine remaining names are frozen in PLAN.json.

## Source changes

This commit descends from the independently formatted lifecycle fixture repair
2cf74e84b85178c9cd9027d771a2bff0a6010dc9. Its draining control uses independent
real durable Agentd fixtures for the cached-state cases; it does not reopen
exclusive prompt-pipeline owners already retained by another live state.

Only production_terminal_owner_tests.rs changes here. No production Rust,
writer-lock rule, authorization rule, parameter limit or caller guard changes.

The first failed factory control already proves that taking and dropping its
bootstrap cannot reset the original owner's once-only assembly claim: the
second factory call on that same Config must still return `already assembled`.
The earlier fixture then incorrectly expected a fresh Config to reopen the
same identity while a pre-assembly clone retained its original writer lock.
The corrected control releases the additional writer reference, retains that
real clone, and requires the fresh Config load to return the original live
writer-lock error. It drops the clone only after this assertion.

This is an explicit correction of the earlier evidence scope. The fresh Config
does not reach the factory's compare-and-exchange. Sharing Arc<AtomicBool> across
host clones remains a source-level fact, not a newly executed cross-clone CAS
control. No test-only production setter, lock release or fabricated Config is
introduced to manufacture that result.

The replay control previously requested expiry 4,000,000,000. The actual Memory
grant rule uses SystemTime and admits only a positive lifetime of at most
31 days. The fixture now derives real current seconds and checked-adds one
hour. The Memory rule and both original live-writer fences remain unchanged.
The real grant and its actual pre-recovery rows still enter the recovery cut.

## Bounded verification

Run only the nine exact names in PLAN.json. They are the original 28 names minus
the 19 named PASS records; no successful control or model fit is repeated.
The unchanged cancellation control and both unchanged factory functions were
compared byte-for-byte against the parent sources. The grant helper is used
only by the originally failed replay control.

The shared engineering pool remains 3,600 seconds. Original measured receipts
give 2,967.9046997300616 seconds spent and 632.0953002699384 seconds remaining.
The remaining-nine command has a 240-second cap plus 66 seconds reserved for
cleanup. One subsequent scoped `just fix --locked -p codex-hepta-agentd` has a
260-second cap plus 66 seconds for cleanup. These are prospective allocations
within the existing pool, leaving 0.0953002699384 seconds unreserved. Record
actual outer elapsed time and owned-child cleanup; do not reset any pool.

The required actual `just fmt` completed with exit zero. Its original result
and compressed postimages are retained beside this protocol. Native execution
is pending when this protocol is published. Preserve any refusal, compile
failure, timeout, partial result or unknown result. No tests follow scoped fix.

These are authorized synthetic engineering fixtures. They establish no genuine
user consent, genuine external trace labels, scientific quality improvement,
real adoption, external utility, payment or foundation-model capability gain.
All original E1-E6 budgets and negative or UNKNOWN observations remain intact.
