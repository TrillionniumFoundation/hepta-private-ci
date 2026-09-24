# Hepta native shell — current-source candidate

Canonical candidate: `work/ui-native-current-source-20260925`, based on main
`7ddbfac88525196e7a4b31387ceae194958275f5`.

This branch carries the actual Rust application files recovered from #830, not
just its merge history. It keeps current kernel owner sources and does not
restore historical authority or gateway implementations.

Read [DEVELOPMENT.md](DEVELOPMENT.md) for the current contract and remaining
repository work. `HISTORICAL_830_DEVELOPMENT.md` is historical reference only;
its Windows/store/product-closure claims are not current acceptance facts.

The narrowly scoped current-source workflow materializes reviewed adaptations,
formats them, commits a native Cargo lock and source fingerprints, then tests
that committed source and a deterministic merge on three operating systems.
The preparation commit is not itself qualification. Actual outcomes are
retained as artifacts, including failures and skipped steps.

No production activation, signing, platform acceptance or release is claimed.
The current main gateway does not yet provide the keyring authentication
expected by the Rust backend; ordinary connected product acceptance remains
blocked until that owner integration is implemented and tested.
