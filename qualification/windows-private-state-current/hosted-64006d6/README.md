# Exact Windows ledger fixture failure and narrow successor

The original run of `64006d610208b0ff346f484265cd5597ceb971f0` passed the
positive acquisition lane and both real production mutation controls. Complete
path-utils, contracts, and Prompt Registry libraries passed 17, 131, and 28
cases respectively. Agentd ran 165 cases: 160 passed and five failed, with zero
skipped. All five failures occur at the fixture directory `File::open` with
Windows access denied, before ledger behavior assertions. Scoped Clippy was
not reached. The original JUnit and acquisition manifest are compressed here
without changing their bytes; sizes, hashes, and the original artifact digest
are recorded in `observed-results.json`.

The successor takes only the existing `open_ledger_directory` helper and two
fixture callsites from the recorded upstream file. Windows opens the actual
owned temporary directory with read/write access and backup semantics; other
platforms retain ordinary directory opening. `LedgerWriter::from_durable`
still checks and synchronizes both actual directory handles and propagates
any failure. No production code, ACL, identity, ledger/witness protocol, test
body, or original assertion changes. The unrelated upstream key and signature
conversions are excluded.

All five original cases are also required by name in the complete-library
qualification. The full current three-platform native and original Bazel gates
must run again. This candidate remains DRAFT / SHADOW_ONLY / DENY_ALL /
HOLD_NO_GO until those current results are verified.
