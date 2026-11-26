# SQLx fixture continuation

This candidate completes only the unfinished part of original run
45738227995, attempt 1, job 139636557660. The original run remains failed.
Root's exact partial-main reuse receipt accepts only the main Cargo lock,
unchanged Bazel lock and original main graph. It does not authorize execution.

## Fixed lineage and inputs

The combined candidate must have sole parent
b4fa4fdd1d05603c1a091930b70f83ec1af73797, tree
73e1ccd4245498fb583326667884953dbdfccbf3. Its main Cargo lock is the actual
421756-byte bc8b1abe42bdb85aa10a9ba2a0c3f022af07bc08e38ac50e94442e58806f9ae1
postimage from that failed original. MODULE.bazel.lock stays byte-identical.

Each independent fixture receives a create-only physical copy of this bc8 seed.
The dependency-edge ceiling is the original 421800-byte d30163218a74e0d8246e709a82c2547fa3306515728b4b9784d0df4034b6c312
lock in the b4fa parent. Its Git blob, size and SHA256 are verified before use.
This distinction allows the explicit Chrono fixture to restore its requested
Chrono edges without permitting new versions, checksums or foreign edges.

All Cargo manifests, Cargo configuration and toolchain files must be byte/mode
identical to b4fa. Automatically discovered target paths must also be identical.
Reviewed Rust body changes can coexist with this continuation; they do not
inherit native qualification from an earlier tree.

## Why the command changes

The observed Cargo is 1.96.0, source commit
30a34c6821b57de0aaec83a901aca39f88f6778c. Its official implementation is authoritative:

- src/cargo/ops/cargo_update.rs: generate_lockfile calls the resolver without a
  previous resolve; update_lockfile loads the existing lock. With --workspace
  and no package selection, its keep set retains nonworkspace dependencies.
- src/cargo/ops/resolve.rs: kept previous package identities become the resolver's
  locked preferences and yanked whitelist.
- src/bin/cargo/commands/update.rs: --workspace is a stable exposed option.

Source URLs are under
https://raw.githubusercontent.com/rust-lang/cargo/30a34c6821b57de0aaec83a901aca39f88f6778c/
The prior empty-lock solve failed on yanked clipboard-win 5.4.1. No version or
advisory is upgraded, suppressed, or declared fixed by this source proposal.

## One bounded sequence

The original artifact does not include a portable Cargo cache. On a fresh runner:

1. Run one cargo +1.96.0 fetch --locked against the accepted main lock, with a
   fresh isolated CARGO_HOME and no retry. Verify both main locks stayed identical.
2. Copy bc8 to the absent default fixture lock. Run one update --workspace
   --offline, then one metadata --locked --offline --filter-platform
   aarch64-unknown-linux-gnu --format-version 1.
3. Independently copy bc8 to the absent compatibility fixture lock and perform
   that fixture's one update and one locked graph observation.

The two fixtures share the restored cache but have separate workspaces, lock
files and target directories. The exact five Cargo commands and their actual
elapsed times are checked. No generate-lockfile, main update, main metadata,
Bazel command, original twelve-control run, native test or retry is invoked.

## Budget and evidence

The original ceilings stay checkout 120, tools 180, generation 900, whole job
1320 seconds. Observed spent values are 13.027237997, 15.091586110999998,
50.812052642000005, and 98 seconds respectively. The 79.133119422-second original
readback is nested inside the old 98-second job. The 4120-second old queue is
retained separately. Neither is added twice or used as runtime allowance.

The separate Root admission bounds checkout at 60, tools at 120, continuation
at 840 and the whole job at 1200 seconds. The 21 new finite data controls passed
once with no skips on the exact formatted data source; their original receipt
SHA256 is e54e976bde8ebb11797e7e64521a2f5e404b5299c3bb561658f4d0c51dda18fc.
These controls do not establish resolver or native success. The workflow is
restricted to the first opening of the named owned Draft. Its job watchdog is
20 minutes. The original
WNOWAIT child owner clips every command to the same absolute phase and whole-job
deadlines, reserving collection/upload time. Failed partial locks and original
stdout/stderr remain evidence. Final job and upload costs still require original
GitHub readback; pre-upload success is not a complete cost acceptance.

## Combined source binding

The paired specifications bind the exact forty publication paths, final source
pins and separate Root admission. All changed paths require exact byte/mode pins except this spec
itself and the one literal peer path
scripts/hepta_chrono_hooks_cli_native_inputs_v2.json. That sole peer exception
breaks a cross-spec hash cycle: native48 pins this final SQLx spec. It does not
exempt the native owner, workflow, executable source, manifests or other JSON.
The peer's schema, activation/blockers, branch, parent, publication list, original
lock acceptance, roster, tools and caps are checked independently. Root retains
both complete final specs and the actual complete Git tree outside the cycle.
The event head/tree are observed from Git and fully retained, rather than
impossibly embedded as self-referential hashes inside the candidate spec.

The source includes the separate Root execution admission. The accepted reuse receipt remains unmodified and explicitly denies
execution authorization; only the separate admission grants the bounded
unfinished continuation. The 21 new data controls live in qa/b4-no-bypass and
are discoverable by existing CI; the dedicated continuation does not execute
them or replay the old twelve controls.

Four lock candidates and two observed graphs require a new independent Root
acceptance before native12+3 can activate. Native48, advisory closure, scientific
learning, speed, adoption and FinalUse remain separate outstanding claims.

The completion owner and final readback both require the retained fixture lock
pin to equal the pin recorded beside that fixture's original graph. A later
fixture step cannot silently replace an earlier lock after graph observation.
