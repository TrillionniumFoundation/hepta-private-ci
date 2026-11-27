# Memory caller inventory and platform boundary

This follow-up extends the retained unified caller manifest from 1,624 to
1,644 boundaries and from 809 to 818 protected files. Every original boundary,
protected-file requirement, ignored-path rule, and false authority flag is
preserved. Five existing rows gain only the explicit product caller required
by the reviewed Memory implementation:

| Existing boundary | Added caller | Reason |
| --- | --- | --- |
| Production writer host open | `native_memory_host_bootstrap.rs` | Explicit Linux compatibility bootstrap, pinned recovered source, exact current cut, and refusal to replace installed owners |
| Final-use state open | `native_memory_host_bootstrap.rs` | Same retained bootstrap, with explicit clock and issuer state |
| Raw final-use claim | `hepta-ndu/src/owner_current.rs` | Current projection read bound to authenticated snapshot and revocation state |
| Raw verified final-use delivery | `hepta-ndu/src/owner_current.rs` | Same current projection proof, checked again after the guarded read |
| Revocation-feed verifier construction | `native_memory_host_bootstrap.rs` | Pinned feed key, strict signature, freshness, and matching authority frontier |

The 20 new boundaries cover six production-writer memory-cell operations,
five current NDU read operations, two current objective checks, and seven
configuration, registration, context, control, model, and worker entry points.
Unique method names use a conservative lexical closed set that includes every
matching receiver spelling. No variable-name exception or new type-inference
shortcut is added. Shared generic methods are covered by explicit function
order and source requirements in their owning files.

Nine protected-file rows require the actual bootstrap, admission/finish,
NDU read, registration, current-context, model dispatch, process lifetime,
tick transaction, and control-delivery fences. The requirements include
pre-model checks, current owner and source revalidation, a single admitted
operation, monotonic observations, owned process cleanup, and post-read or
pre-delivery revalidation as appropriate. These are source checks; they do not
establish runtime authority or execution qualification.

The current Memory fixture support file now repeats its parent module's
`cfg(all(test, unix))` at file scope. This lets the existing scanner recognize
the same test-only boundary that Rust uses. The scanner and ignored paths are
unchanged. The two other fixture support files already received matching
file-level `cfg(test)` in the ordinary merge checkpoint.

## Platform scope

The public CLI bootstrap and native control host are compiled only on Linux.
The model/process implementation is also reachable through library APIs, so
the CLI guard alone did not protect non-Unix callers. The process boundary now
rejects non-Unix platforms before verifying worker files, creating receipt
directories, or spawning a child. A separate non-Unix behavior test exercises
that refusal against an empty temporary directory. It is pending an actual
non-Unix test run and is not counted among Linux regressions.

On Unix, a fresh process group owns ordinary descendants that retain that
group. Cleanup is attempted after normal completion, timeout, cancellation,
and dropped work; cleanup errors prevent success. This does not contain a
descendant that deliberately escapes the group and is not an OS sandbox.
All standard-stream operations have a deadline and bounded output drains,
so a descendant retaining a pipe does not force an unbounded reader join.

Linux additionally verifies the production launcher's reported
`PR_SET_PDEATHSIG` binding to the actual creating parent thread. The existing
launcher explicitly reports that parent-death binding as unsupported on other
platforms. macOS has the Unix process-group path, but no Linux parent-death
qualification is inferred for it. Windows has no newly invented Job Object
owner and cannot return a successful native process result through this path.

## Verification at this checkpoint

The exact manifest and Rust source hashes are recorded in
`callers-memory-focused.json`. All 25 selected boundary rows and all nine
new guard rows passed across 7,476 Rust files. The extension receipt records
the preserved original rows and the explicit additions. The prior full
diagnostic's five failures are retained in `callers-diagnostics-before.json`;
they were the findings this change resolves.

The canonical full-manifest command remains a separate gate:

```sh
python3 scripts/verify_hepta_callers.py verify --root .
```

Native compilation, owning-crate tests, formatting, and unified Cargo/Bazel
lock validation remain independent checks. The presence of a source proof or
test does not count as passing those checks.

## Full scan completion

The canonical command completed successfully on commit
`8ce85627f92ecd9ff6cc21afc75472302eb0bb9d` (tree
`66551efbe5e23ed445b0012cc7c792e451ebca52`): **1,644 boundaries, 818 protected
files, and 7,476 Rust files**, exit 0, empty stderr, in 895.953 seconds. The
worktree began clean, and all Rust files, the manifest, both proof scripts,
and the source commit were verified unchanged after the command.

`callers-memory-full-command.json` binds that result to its commit, exact
manifest hash, complete input inventory, and raw output. The 766,301-byte
original result is preserved losslessly in `callers-memory-full-output.json.gz`;
`callers-memory-full-inputs.json.gz` preserves the per-file hashes. Their
compressed sizes are 59,068 and 351,580 bytes, both below the normal repository
blob limit. The real blob gate also passed on the same commit against the
unified `f41db48d` baseline, with only the exact reviewed asset and manifest
hash pins.

This result is scoped to that fixed source commit. Later formatting, integration,
or source changes require their own applicable proof and native checks; no
runtime authority is granted by this receipt.
