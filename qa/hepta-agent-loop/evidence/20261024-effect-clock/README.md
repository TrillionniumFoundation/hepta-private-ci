# Original-owner clock and effect state guards

The actual gate passed 16 focused clock/effect tests, 357 selected original
AutomationStore/contract-owner tests (10 excluded by the existing test profile
or configuration), and 79 native-loop/qualification tests (zero skipped).
All final invocations explicitly used zero retries. Full dependency graph
Clippy, scoped fix, formatting and diff checks passed. Workspace deny lints were
enforced; advisory warnings were retained.

The first focused run compiled but passed 9 and failed 6 tests. Its async fixture
captured only fields of Security, prematurely dropping the uncaptured TempDir
and deleting the original authority journal. A three-file test-only overlay
retained the whole fixture, exposed early synthetic owner errors and added a
real sync/async directory-lifetime regression. Production timeouts, clock order
and authorization predicates were unchanged. Both the original failure and final
complete logs are retained. Source hashes describe the final formatted files.

The new opaque live clock claim samples the original FinalUse clock, fences the
original new claim, refuses legacy/existing leases and checks time after awaited
admission work and immediately before original driver entry. It does not create
a second authority or reconstruct a cold claim. Generic run/step transitions
cannot erase original admitted-effect evidence; evidence-owned settlement keeps
its original receipts. Multiple non-absent effects conservatively remain
Indeterminate until an actual aggregate-outcome owner exists.

Production clock bootstrap/persisted identity, full native task A/B, provider
budget capability and complete tool/sandbox composition remain separate gates.
No deployed runtime/service was changed or restarted.
