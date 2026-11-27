# Windows retained-file recovery fixtures

The complete Windows run for `fb00e4422c293ffb318c9d7535e1991a3bbac707` executed six state recovery tests: one passed and five failed (203 unrelated tests were explicitly filtered out). Three synthetic retained-file cases returned `Indeterminate` during their preconditions; two actual SQLite cold-image cases failed private-file validation. A separate native primitive probe established that ordinary filesystem creation in that runner produced an owner different from the effective token user. The state log itself mapped those details to `Indeterminate`, so it does not independently establish each underlying owner value.

The synthetic fixtures now establish their required private owner at `CreateNew`, using the already-qualified retained-handle primitive. Existing files are never repaired or overwritten. File and directory flushes propagate their real results. The replacement, sidecar, and occupied-WAL inputs also have valid private ownership so that wrong-owner rejection cannot mask the intended identity, presence, or creation-collision check. All original rejection, unavailable-writer, source-immutability, and candidate-cleanup assertions remain intact.

These fixtures contain raw bytes for retained-file tests. The two tests that create actual databases through SQLx remain unchanged: a fixture-only adjustment does not repair SQLite's default-owner creation behavior. Their required opt-in VFS work is tracked separately. This fixture change still needs its own native execution.

## Additional actual workspace qualification

On the same unchanged registry and path-utils source, with the real workspace and production `Cargo.lock`:

- Registry Linux tests: **50 executed, 50 passed, zero skipped**; 4.204 seconds in the test runner, 24.487 seconds including build.
- Registry ordinary scoped Clippy: exit zero.
- Path-utils library and tests, Windows MSVC target, ordinary scoped Clippy: exit zero in 13.989 seconds. This cross-compile check executed no native tests.
- All 20 checked source files and the dependency lock stayed unchanged. Cargo's unused `imbl` patch warning for this scoped selection is retained.

The earlier isolated-manifest registry result remains separate evidence. This later qualification uses the actual production lock and does not substitute for the complete workspace or Windows consumer gates. `receipt.json` records source and log hashes and these boundaries.

The Windows ownership behavior is defined by Microsoft's [Owner of a New Object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object): inherited access permissions and the token's default owner are separate inputs. No owner or ACL acceptance rule is relaxed here.
