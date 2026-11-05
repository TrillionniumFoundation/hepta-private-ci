# B16: actual state options bind native SQLite custody

## Status and scope

This is a **source-only candidate** following the six B cohorts in serial plan `a46fdc65f78295bfb041732aeb03b1937f85eab9`. Its state base is `b9fb565cadd14f6541bfc8421164897e2907e2ad`; the serial plan was statically aligned against A tree `f8251e1d14fa8524ab469281296cd4cf708f173c`. It is not a patch against unmodified product commit cabcb, and it has not been compiled or run.

Four source paths change, with 355 additions and 9 deletions before formatting. Only **four executable production lines** are added: each explicit state constructor clones its existing `Arc<F>` into `SqliteConnectOptions::connection_lifetime_token` before opening a connection. Existing commit, checkout, recovery and Windows logic is preserved.

The prerequisite SQLx candidate is manifest `9262807373267fe42587a36a50721aa08b60c56b`, full patch `abe067bc6f2ca9601eef83b0cd4e0db4811827ac`. Its actual published source is VCS `003b698e99e024f3621b8043a2426fde5b741171`, with registry equivalence receipt `246b438e9f8026abaa4c48b62dd4d55ffa470cee`. It is still awaiting real repository adoption, manifests, generated locks, compilation and physical controls. This application patch cannot compile against the unchanged registry driver.

## Actual ownership chain

The ordinary Memory opening path already acquires an OpenGuard and captures `CognitiveCommitGate::for_open_guard` in the explicit guarded state callback. Recovery candidate validation and published-store reopening already capture the original exclusive guard the same way. The gate owns the actual File and, on Windows, the original retained directory File.

The new state binding carries this same capture into SQLx options, into establishment before worker spawning, and into the native connection handle before `sqlite3_open_v2`. It therefore closes the caller-side omission that would remain if a dependency offered the token API but the application never passed its owner. The existing commit hook and reserved collation remain unchanged.

The commit predicate remains a monotonic commit interlock. It does not authenticate Current, verify a Root signature, refresh authority at final use, or turn a path or empty callback into a custody owner. The production provided-pool read-only wrapper remains outside this token-bound path and relies on its existing actual cold-image read-only mechanism.

## Three new physical controls

| Selected parent | Evidence required |
|---|---|
| State guarded native-open cancellation | An owned normal libtest child holds the actual File lock; a real SQLite open callback blocks; the actual state future is polled into that callback and cancelled. A different parent process must observe `WouldBlock` while a post-probe gate check still reports 0. After release and native close, the lock must become available. |
| State coordinated initial-PRAGMA cancellation | The same cross-process oracle pauses a real SQLite progress callback during initialization. The checkout callback is a rejecting sentinel and must not be reached. This is a test of the actual coordinated constructor, not an empty successful coordinator. |
| Actual Memory connection after both callback anchors are removed | Open the actual store, detach a real connection and close the store. Test-only removal of the commit hook and replacement of the collation eliminate both prior registered captures. A live SELECT and a separately opened original OpenGuard must still show custody until physical `connection.close()`. No write follows hook removal. This test uses separate File handles in the same process; it is not represented as cross-process evidence. |

The two state parents explicitly launch one ignored support entry. That support entry is not counted as an additional PASS. The fixture owns and reaps its child and reader; no grandchildren are created. Only the new stages have five-second bounds. Existing budgets, skips, retries and permission checks are unchanged.

## Counterfactual and exact reconstruction

Full patch: `223ce97fbdeec446f8baf1f44831954041026321`.

The negative patch `842177e235d729e92e73e82c1ebd4fac2ede7fb2` removes only the four actual state binding lines. All tests, the native token API, the hook and the collation remain present. Restore patch: `40e559a07abbe39d4d796311b09252fc07e43a9d`.

Both state negatives qualify only if the callback actually entered, the future was cancelled, the real lock was wrongly available, and the gate remained blocked after the physical probe. The Memory negative qualifies only after successful opening, live SQL, initial contention and the explicit both-anchors-removed marker. Setup, compile, timeout, selector or earlier SQL failures are not causal evidence.

Static proof `1cf40482a527d548dca08cde2fcda58335a654b8` records three actual isolated `git apply --check` / apply phases and exact four-path postimages. No Rust command or shared/native tree was touched.

## Required execution

After root-approved dependency adoption and real Cargo/MODULE generation, the sole native lane must first qualify the four dependency controls and original driver unit tests. It must then run the three caller negatives, restore the exact source, and run the three positive controls and the original owning state/Memory suites. Use the original `just test`, local profile, locked dependency graph, zero retries and fresh complete JUnit/raw output; require exact selected parent names and keep original ignored/filtered counts separate.

The unchanged four state commit-gate controls, five read-barrier controls, four Memory custody controls, sender/read-ACK/AlreadyRetained and recovery regressions remain required. The existing R2c V3 `sqlite_version()` observation must describe the actual SQLx pool under qualification.

**Still open:** actual adoption and runtime qualification, independent shared-open connections that do not opt in, Current/Root/FinalUse authority, normal producer integration and all original platform gates. Static source ownership is not project or B16 completion.
