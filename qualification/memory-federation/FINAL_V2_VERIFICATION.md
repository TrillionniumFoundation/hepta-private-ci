# memory.federation current verification

Canonical continuation: PR #990, `work/product-convergence-20260923`.
This record supersedes the old `395244ed...` / #935 frozen-candidate receipt;
that historical receipt is not evidence for current source or tests.

## Candidate and claim boundary

The current candidate binds local reads to the memory owner's published generation,
rejects retained readers/attachments after recovery, and collects healthy discovery
results within a one-second sub-budget of the existing two-second request horizon.
It preserves read-only ownership, canonical V2 response/authority checks and the
separate lifetime-exclusive recovered writer fence.

Source identity is recorded by the current implementation map. Source navigation
verification is not executable qualification. `productionImplementation`,
`productExecutionProved`, independent acceptance, activation and release remain
false until the complete applicable gates have actual passing receipts.

## Required execution on the frozen source and current-main merge

Use the same commands in `.github/workflows/memory-federation-v2-final-verify.yml`:

- exact source/tree verification and current implementation maps;
- selected package formatting;
- canonical federation contract tests;
- memory runtime, recovery and legacy federation tests;
- memory-extension attachment/final-use tests;
- the actual Core HTTP final-use guard regression;
- Agentd/App Server compilation and strict product all-target Clippy;
- clean tracked-source verification.

Tests use the repository `just test` / nextest entrypoint with locked dependencies
and zero automatic retries. A timeout, compilation-only result or older candidate
pass must never be relabeled as current successful execution.

## Local capacity experiment

The explicitly ignored `federation_product_local_capacity_measurement` fixture
opens real SQLite owners and measures 100 recall plus final-revalidation samples
at 1, 4 and 16 peers with eight records per peer by default. Set
`HEPTA_FEDERATION_MEASUREMENT_RECORDS=128` for the denser bounded fixture.
The report includes DB/WAL byte counts and Linux process peak RSS. It reports every sample and
p50/p95/p99/maximum latency after fixture construction, while asserting complete
coverage and current bindings. Run it explicitly with `just test --locked
--retries 0 --run-ignored only -p codex-hepta-memory --lib -E
"test(federation_product_local_capacity_measurement)"`.

Its bounded harness allowance covers durable fixture construction, not a wider
product deadline. This debug smoke is not long-history, RSS/I/O, overload, power-loss
or production latency qualification. Those measurements remain required.

## Remaining implementation and external qualification

The shipped adapter is local owner-store federation, not an authenticated network
transport. Cross-host deployment still requires an implemented, registered wire
profile, owner/peer credential binding, portable current-cut evidence, live
revocation, and real two-host fault/recovery qualification. The local path/inode
generation digest is explicitly not a portable remote identity or cut witness.
No cross-host or deployment claim follows from these local fixes.

Product cancellation still uses the existing host future-drop boundary; canonical
cancellation receipt attribution remains an explicit observability gap. Production
acceptance and release are not granted by this record.
