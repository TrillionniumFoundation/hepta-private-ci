# P2e: actual Codex protocol differential qualification

This additive research successor is based only on P2d repair #2150,
`a2d9d5ef229e5dc2ea3baee4e60195b40b3ff056`. Its parent preserves the original
Evidence SQLite recovery owner and P2c deny-only preflight. No production source,
Cargo dependency, lockfile, permission, effect route or durable schema is changed.

## Three actual readers, one frozen raw-byte corpus

1. `codex-hepta-contracts` invokes the existing
   `inspect_codex_exec_server_start_v1` on all 50 raw requests.
2. The repository's real `codex-exec-server-protocol::JSONRPCMessage` and
   `ExecParams` deserialize the same bytes. This is not another hand-written
   simulation of the upstream types.
3. A separate upstream checkout is pinned to OpenAI Codex `rust-v0.162.1`, commit
   `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`. Its actual `JSONRPCMessage` and
   `WireExecParams -> ExecParams` ingress consume the identical corpus and
   shared probe. The **original tracked upstream checkout remains unmodified**.
   A second detached worktree contains the same exact upstream code plus the
   three untracked test files and a strictly qualified **local-workspace-version
   normalization** of its release Cargo.lock, detailed below.

The original P2c already uses `argv`, `processId`, a `file:///` cwd and `tty`.
It is incorrect to describe that exact implementation as accepting `command`
and a plain filesystem cwd. This suite does not claim to fix such a defect.

## Reproducible upstream release lock qualification

The initial native source-head/base-merge CI exposed a reproducibility issue in
the immutable upstream tag **before upstream tests could start**. Its recorded
Cargo.lock Git blob is `1cee1174c2e937758713df47683521233a36b4f7`.
The original checkout reports 161 local workspace packages as `0.0.0`,
although the pinned tag's workspace release version is `0.162.1`.
The original hosted Cargo resolution artifact from [run 38850446447]
(https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38850446447)
showed **161 version-line changes only**, with zero changes to any third-party
dependency version, source URL, checksum or Git revision.

Rather than disabling `--locked`, or modifying the upstream checkout, the CI
creates a **second detached worktree at the exact same pinned commit**. The
independent `scripts/hepta_exec_p2e_release_lock.py` verifies both checked-out
HEADs and original lock blobs; requires exactly 161 zero-version packages,
each without an external `source` or `checksum`; rewrites only their local
version values to `0.162.1`; re-parses and compares every TOML lock package,
refusing any other difference; and verifies the sole tracked change in the
qualified worktree is Cargo.lock. An exact SHA-256 and Git blob for the derived
lock are emitted into retained CI evidence. Ten synthetic adversarial unit
tests exercise refusal cases for the normalizer. The **original pinned
upstream checkout and original Cargo.lock stay unchanged**. The actual upstream
`WireExecParams` integration test and strict Clippy still use `--locked`,
against the qualified lock in the separate worktree. Final audit revalidates
the same derivation and records the qualified lock digest.

This is a transparent *derived release-version lock qualification*, not a
claim that the tag's shipped lockfile passes `--locked` unchanged. Any
different dependency graph, source or checksum is a hard failure. No production
Hepta dependency, executable, final-use authority or execution permission
changes. Even a fully successful run proves only the frozen 50-case parser
subset, not the physical Exec Server effect boundary or effective sandbox.

## Expected profile distinctions, not grants

The corpus fixes 6 Hepta-admitted inspection examples, 30 native-deserializable
start requests and 20 rejected native-start examples. Counts are **expectations**
until the native jobs actually complete. Fifty corpus cases in a loop are not
fifty independently registered Rust tests. The suite adds one Hepta integration
test and one shared native integration test, run against two real libraries.

Unknown fields, explicit policy fields, interactive flags, process/RPC identity
mismatch and larger argv are intentionally outside P2c even where upstream can
parse them. Extra whitespace/member reordering requires a different final-byte
binding. Duplicate keys must not be normalized away before parsing.

Native parsing is not runtime execution validation. In particular the accepted
P2c profile decodes to `sandbox=None` and `enforce_managed_network=false`.
That is **not proof of an enforced OS sandbox**, nor permission to execute
unsandboxed. `env={}` and `env_policy=None` are recorded as decoded data only;
this suite makes no claim about the effective launched child environment.
No shell, target process, effect owner, grant issuer or network endpoint is
invoked by these probes. Cargo/CI and Git provenance commands are build tooling,
not application effect dispatch.

## Evidence and failure rules

`scripts/hepta_exec_p2e.py` pins the exact corpus SHA-256 and rejects missing,
duplicate, extra, semantically changed, authority-positive or incomplete result
rows. It requires successful native test footers, fixed upstream HEAD, original
parent ancestry and clean tracked source trees. Reports include the actual tested
commit/tree and raw log SHA-256 values. These are CI observations, not independent
signatures or production authorization. Failure logs remain retained; there is no
synthetic fallback and no source-head result is inherited by a prospective merge.

The 10 auditor Python tests use explicitly synthetic rows to attack the auditor.
They do **not** execute Rust, validate an upstream binary, or prove conformance.
The local `--validate-only` output explicitly says `native_tests_executed=false`.

Run the auditor tests and corpus integrity check locally:

```sh
python3 -m unittest discover -s scripts/tests -p test_hepta_exec_p2e.py -v
python3 scripts/hepta_exec_p2e.py --corpus qualification/codex-exec-p2e/corpus.json --validate-only
```

The P2e workflow builds source-head and prospective-base lanes separately with
locked Cargo, real Rustfmt, original contracts/Evidence/protocol regressions,
strict Clippy and exact-source verification. It then compares all three native
readers. It deliberately does not import a new executor crate into Hepta contracts
or change the production dependency direction.

## Remaining prerequisites

Even successful native conformance does not qualify tool dispatch. The original
owner still needs independent signed Final-use at entry, authenticated executable
and target identity, effective environment/sandbox custody, pending-before-effect
ordering, independent terminal reconciliation, cancellation and crash/power-loss
proof, target-host measurements and operator admission. Global security and
architecture gates are not waived. No extraction, Cell Split or merge to main is
authorized. This change contains no throughput/CPU/RSS/p99 improvement claim.

**DRAFT / DENY_ALL / NO PRODUCTION ROUTE / NO CODEX FORK.**
