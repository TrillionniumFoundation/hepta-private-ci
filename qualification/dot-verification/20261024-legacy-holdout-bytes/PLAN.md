# Legacy file-byte migration, not Rust source compatibility

Old production source: b98961ceb71414490e1c6ae397cf635bca3093f4.
New production source: b2964156764e174b396407c0c981d6fad043b204.
Both isolated worktrees use the repository Rust 1.95.0, locked dependency graph,
normal official Cargo registry, jobs=1 and a separate build target directory.
No provider, socket, model, census or CI execution is part of this task.

The old integration generator calls the actual old LockedFileFinalHoldoutCasStoreV1
and FencedFinalHoldoutOwnerV1. It writes a fresh header/fence/legacy OPE consumption,
closes the owner, then records original file bytes and independently retained
anchor/receipt/head. No replacement writer or hand-assembled journal qualifies.
The old tree receives only the generator test; production files stay unchanged.

The new regression must read those immutable bytes with the actual new reader,
validate the original anchor/head/receipt, repeat the old consumption without an
append, append a paired plan, preserve the full original prefix, close/reopen,
and replay both consumptions without duplicate entries. A corrupted fixture and
a restored old prefix below the new retained anchor must fail closed.
If anything fails, preserve it and diagnose without rewriting the old fixture.

This establishes a tiny concrete old-file migration case only. It does not
establish public Rust type compatibility, all persisted historical formats,
production permission, power-loss atomicity, or scientific NDU effectiveness.
