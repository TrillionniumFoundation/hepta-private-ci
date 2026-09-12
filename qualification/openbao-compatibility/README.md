# OpenBao compatibility gate

This directory is the repository-owned compatibility ledger for the goal of
replacing a specified OpenBao release. It is a blocker ledger, not an
implementation claim and not a release or production authority.

Run the gate from the repository root:

```text
python3 scripts/verify_openbao_compatibility.py
```

The gate fails while any blocking capability is `gap` or `partial`. A row may
move to `closed` only when its evidence paths exist, the native implementation
and named product caller are present, the versioned interoperability tests pass,
and the applicable independent operational evidence is recorded. A documentation
file or source directory alone is never sufficient.

The target is a pinned OpenBao version and deployment profile. API, storage and
seal compatibility are separate dimensions; a partial API adapter cannot be
treated as a storage or seal replacement. The current matrix deliberately
records the narrow HeptaBao KV v2 consumer as `partial` and keeps every other
OpenBao capability blocked until its implementation and evidence are complete.
