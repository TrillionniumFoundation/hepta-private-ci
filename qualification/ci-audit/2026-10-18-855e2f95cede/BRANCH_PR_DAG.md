# HEPTA branch / PR evidence graph

Repository: [TrillionniumFoundation/hepta-private-ci](https://github.com/TrillionniumFoundation/hepta-private-ci). Collection interval: **2026-10-18 14:20:04–14:23:41 UTC**. This is a complete paginated collection over an active repository, not an atomic GitHub snapshot.

## Coverage and exact counts

| Collection | Observed count | Completion evidence |
|---|---:|---|
| Branches | 2,519 unique names | 26 data pages, page 27 empty; no duplicate names |
| Pull requests, all states | 2,846 unique IDs | Pages 1–29, page 30 empty; IDs exactly #1–#2846 |
| Open PRs | 1,553 | 1,526 Draft + 27 non-Draft |
| Closed PRs | 1,293 | 315 merged + 978 closed without merge |

All requests used allowed GitHub plugin `github_fetch` REST collection GET with `per_page=100` and explicit `page`. PRs used `state=all&sort=created&direction=asc`; no search result cap or first-page count is presented as total. Raw responses are retained as JSON or lossless gzip with hashes and query timestamps.

Observed main: `f8c9419df6ddeb36ff8b522a50219981fb8d9345`, protected=True.

## Evidence semantics

Branch → PR bindings and PR base refs are VERIFIED_NOW metadata. Active parent PRs below match the actual base ref. They are not a proof that the child contains the latest parent commit. Body mentions are retained separately and are never promoted to a dependency edge. GitHub author/assignee identities do not prove a unique live Agent owner.

No PR was closed, merged, retargeted, pushed, or promoted by this inventory subtask. No complete diff/review/CI/security/science acceptance is inferred from a title, Draft state, branch name, mergeable flag, or old success.

## Requested historical roots and current competing lines

| PR | State | Draft | Head SHA | Base ref | Active parent PR | Scope |
|---|---|---|---|---|---|---|
| [#1504](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1504) | open | true | `79db9bdc19d6960e8350fae310755db12938304b` | `main` | — | P0/P1/P2: exact five-boundary Chain pair and failure-preserving full-baseline delivery |
| [#1500](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1500) | closed | true | `779d0c744d75c5b04404f3492a11d9e269afaf8e` | `main` | — | P0/P1/P2: converge canonical migration recovery and the unified hostile-business native pair |
| [#1501](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1501) | closed | true | `7941d7050c3432214c7af996ede65b6ed027a3bf` | `main` | — | P0/P1/P2: final exact-source pair retaining complete native evolution and hostile-business controls |
| [#1468](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1468) | open | true | `8b8a1b74a9340ae0a40114bc1116945838e79be1` | `codex/hepta-bounded-inference-scale-20261009` | #1465 | fix(hepta): strict final-use request binding, batch telemetry, signed-owner CI gates |
| [#1508](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1508) | open | true | `aa0d5f9e863c0bd24b642b4eb2bb48528ea6220f` | `codex/hepta-production-gates-20261010` | #1468 | fix(hepta): persist independent Cell Split owner pins and reject noncanonical replay |
| [#1509](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1509) | open | true | `8032a73a83a71c9a99eba91eec8a4516515c91c2` | `codex/cell-split-ledger-trust-pins-20261011` | #1508 | style: exact rustfmt for cell split tests |
| [#1452](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452) | open | false | `2a0e8d016f5e00359561934909e801ae26f2bfd7` | `main` | — | feat(memory-cell): complete native census, bounded serving and adjudication handoff |
| [#1390](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1390) | open | false | `3589a2964d1aa5fd6119e2dd9a363ab4579a981b` | `fix/main-product-blockers-20261005` | #1389 | fix(acceptance): verify pinned SSHSIG without Unix subprocesses |
| [#1278](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1278) | open | false | `c142eae6fa3a6ef4da3074541a649d5241170d04` | `main` | — | automation.taskflow: harden durable recovery, provider identity and circuit evidence |
| [#1237](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1237) | open | false | `e3e4e650bd6f57aaf520193a6b2febab42e6f9d3` | `main` | — | learning.operator: single-candidate semantic qualification and readiness convergence |
| [#1234](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1234) | open | false | `92f8715dc5d3ea0060447744312eb494e76babe4` | `main` | — | ci(inference): bootstrap trusted artifact acceptor |
| [#1001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1001) | open | false | `18654890257ad54e628445731288df011f679361` | `main` | — | platform.types: close protocol, wire, owner, and exact-candidate qualification gaps |
| [#2695](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2695) | open | true | `29fceb086d0f8cc9073664f38ae6dd419a933f03` | `main` | — | feat(neuron,ndu): shared Encoder, Cell heads, runtime evidence |
| [#2747](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2747) | open | true | `a634e2d2bac429debdb2b2c09f4edce6589b221d` | `fix/security-zip-20261017-v4` | #2717 | [DRAFT] integrate real Windows portability fixes on security P0 |
| [#2790](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2790) | open | true | `55ad95747cec6d7bf122b1e825eda25fc08f4b36` | `integration/security-windows-baseline-20261017` | #2747 | [DRAFT][security] Qualify sync Linux keyring backend without zbus 4 |
| [#2789](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2789) | open | true | `59ed05c0c79ebc73834aa48ace640a86a710843b` | `codex/group-ndu-deterministic-20261017` | #2695 | [DRAFT][P0] Resolve ZIP 9 on exact shared-Encoder security parent |
| [#2800](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2800) | open | true | `72ea1527b8bf0af5d3d79fffc7bbfc24ac7fa788` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | [DRAFT][P0] Integrate exact-source Fleet/Agentd/Automation Clippy fixes on Cell base |
| [#2805](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2805) | open | true | `e29db69ff115d1dcf5778e84ba5ff8e715fc472b` | `integration/security-windows-restart-fleet-clippy-20261018` | #2753 | [DRAFT][CI] Route cognitive schema oracle SQLite fixture through canonical shim |
| [#2813](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2813) | open | true | `88994f6bf50e4336beca3d5ce2c760192ea523a6` | `main` | — | test(windows): bind federated Memory final-use fixture to round-tripped PathUri identity |
| [#2688](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2688) | open | true | `b5e61ecb07adcc7e41928a3ba27ca78dcde03aaf` | `main` | — | feat(cognitive-types): add shadow-only Memory Cell contracts |
| [#2815](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2815) | open | true | `2be5fc052ae7b2e9fb08c68a3ae7e5a218ad37d5` | `main` | — | feat(hepta-agentd): read exact durable Objective admission through owner |
| [#1350](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1350) | open | true | `d8edbcc0118b5ec33a1d513663520ea6305ec7f1` | `codex/intuition-policy-production-closure-20260927` | #1036 | test(agentd): propagate kernel evidence fixture errors |
| [#2599](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2599) | open | false | `1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e` | `main` | — | ci: remove clippy denied unwraps from test fixtures |

## Maintenance donor review: actual kernel-evidence Clippy failure

- #1350 contains the exact typed Result fix for `kernel_evidence_product.rs`: two fallible helpers, 13 outer callers, parser String errors converted through `anyhow::Error::msg`, and serialization context preserved. Donor postimage is `6d2ffd978bb926f941dd17a66011060079f2fabd`; main preimage is exactly `a3e546830527f214c08b6a367c0f708b26a3e9d2`.
- #1350 is stacked on #1036, not main. Its main merge-base is `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`, with main-side 8 commits and feature-side 218 commits. The main comparison includes substantial Intuition code, workflows, lock changes and maps. Its four old map changes must not be blindly copied into main.
- #2599 is the existing bounded maintenance owner on actual main `f8c9419df6ddeb36ff8b522a50219981fb8d9345`, ahead 5 / behind 0. Fresh metadata observed head `1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e`, open/non-Draft and mergeable but blocked. Its exact four changed source paths are test fixture code. The original replacement discarded underlying errors via panic closures and retained a Fleet `unwrap_err()`; the isolated refinement preserves errors through Results and retains exact revocation assertions. Publication and current-head CI remain separate root-owner work.

## Current non-Draft open PRs: review inventory, not merge authorization

| PR | State | Draft | Head SHA | Base ref | Active parent PR | Scope |
|---|---|---|---|---|---|---|
| [#994](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/994) | open | false | `5fb67266c83b1d7ef41be7fb765fdfecfa24ad5f` | `main` | — | objective.compiler: close projection, protocol, and qualification gaps |
| [#1001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1001) | open | false | `18654890257ad54e628445731288df011f679361` | `main` | — | platform.types: close protocol, wire, owner, and exact-candidate qualification gaps |
| [#1038](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1038) | open | false | `b196e2dbec0e0a634e60f7eaeff329afed6afad7` | `main` | — | cognitive.store: close product boundary, signed bootstrap, qualification, and lifecycle gaps |
| [#1069](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1069) | open | false | `5c0bbe30e4a5d408c430e8ab1fcc25638042d82a` | `main` | — | ui.control: isolate recovery and harden browser control boundaries |
| [#1083](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1083) | open | false | `5e36ad2d4952992571b60cd02068ad06c2765ddd` | `main` | — | memory.federation: converge qualification, runtime, and authenticated wire boundary |
| [#1140](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1140) | open | false | `2063e41e089bb486e0936044593decab0b6194c2` | `main` | — | fix(ndu): converge A–D hardening, recovery, retention and exact qualification |
| [#1160](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1160) | open | false | `82c72395a64b97d8beb1f76901d66fe7fc06e4db` | `main` | — | architecture: converge scalable module and runtime boundaries |
| [#1179](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1179) | open | false | `5b2ac550ba31197db1cb4a6946df11d14973baa3` | `main` | — | runtime.codex: add protected real-provider qualification and operations runbooks |
| [#1199](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1199) | open | false | `87f3d1d99029a357d1babeeeaa09c6d97364dce0` | `main` | — | prompt.registry: close qualification and evidence identity |
| [#1227](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1227) | open | false | `058c16cb7ade579b52b5235e51bb655a8ee46087` | `main` | — | fix(memory.retrieval): close lifecycle, bounded product admission, and durable recovery contracts |
| [#1234](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1234) | open | false | `92f8715dc5d3ea0060447744312eb494e76babe4` | `main` | — | ci(inference): bootstrap trusted artifact acceptor |
| [#1237](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1237) | open | false | `e3e4e650bd6f57aaf520193a6b2febab42e6f9d3` | `main` | — | learning.operator: single-candidate semantic qualification and readiness convergence |
| [#1278](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1278) | open | false | `c142eae6fa3a6ef4da3074541a649d5241170d04` | `main` | — | automation.taskflow: harden durable recovery, provider identity and circuit evidence |
| [#1390](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1390) | open | false | `3589a2964d1aa5fd6119e2dd9a363ab4579a981b` | `fix/main-product-blockers-20261005` | #1389 | fix(acceptance): verify pinned SSHSIG without Unix subprocesses |
| [#1452](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452) | open | false | `2a0e8d016f5e00359561934909e801ae26f2bfd7` | `main` | — | feat(memory-cell): complete native census, bounded serving and adjudication handoff |
| [#1682](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1682) | open | false | `e89570ddb8bd21c8c89d6278456014d8245c745a` | `main` | — | Add shared Stem, Head matrix, and governed fast paths |
| [#2273](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2273) | open | false | `f6c9d1d00bd927aa81ced02a6df81670515c963d` | `main` | — | feat: add NDU resource portfolio and snapshot-bound shadow pipeline |
| [#2365](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2365) | open | false | `da3f14b9b16bb8d6d4b4e29f2315b3c379908b84` | `codex/memory-cell-evidence-20261008` | #1452 | feat(memory-cell): experimental associative memory kernel with matched type-split and artifact-only tests |
| [#2406](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2406) | open | false | `fd3811f84f044a107d58a20e0ef59bd29013f232` | `main` | — | fix(actions): allow CI aggregate jobs to stop on cancellation |
| [#2566](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2566) | open | false | `abb2c24f5e95fa189da2a40959d9a9b175daa0bb` | `main` | — | CI: real 500-job fanout with source-pinned shards and live capacity audit |
| [#2599](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2599) | open | false | `1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e` | `main` | — | ci: remove clippy denied unwraps from test fixtures |
| [#2605](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2605) | open | false | `5b943a0aeefdbfe7fff8d27a2d5060f4b47b2463` | `main` | — | security: update rustls to patched 0.23.46 |
| [#2606](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2606) | open | false | `28607454e2c648bc1ee7e4c31acffd976652829e` | `main` | — | docs: record remaining cargo-deny security blockers |
| [#2607](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2607) | open | false | `db2f44be8703701e944da54678c6a0b6e7139008` | `codex/memory-cell-evidence-20261008` | #1452 | feat(memory-cell): original-byte factorial controls, real Reader evidence and bounded pairing |
| [#2611](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2611) | open | false | `cc594bbb1494f3dc3f5adff360a58eee958f2054` | `main` | — | research(ndu): SNG-R short-horizon FBSDE shooting and DAG shadow reference |
| [#2697](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2697) | open | false | `5810df76d82c4189e2ff8bd6da55d21adf5a646d` | `main` | — | fix(agentd): authenticate control socket peers before frames |
| [#2709](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2709) | open | false | `db3dca79d410976a074e0a13e88c3ebd20d9975f` | `main` | — | fix(app-server): authenticate Unix control peers before WebSocket upgrade |

## New current lines after the handover list

| PR | State | Draft | Head SHA | Base ref | Active parent PR | Scope |
|---|---|---|---|---|---|---|
| [#2816](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2816) | open | true | `6b36545af86e8c9f2cfa0d29f81c67e84f1e9f09` | `fix/neuron-durable-pre-dispatch-intent-20261018` | #2770 | fix(auth): restore closed caller proof on durable Neuron dispatch-intent owner |
| [#2817](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2817) | open | true | `8c28cd75716a8359ed4bd153e2b97de1293d0d06` | `main` | — | [DRAFT][P0] Commit observed Cargo/Bazel lock repairs and build fixes |
| [#2818](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2818) | open | true | `5b25b9e8e10101b519079425d55f8e5b65ed98ee` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | [DRAFT][P0] Restore strict Cell Split observer validation and exact Ruff formatting |
| [#2819](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2819) | open | true | `1bd871a608055cbc59f25c0a216e834a1163377b` | `main` | — | security integration (draft): #2717 with repaired Cargo.lock and rustfmt |
| [#2820](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2820) | open | true | `c197d2925d99eb78de201d91477f18431a960971` | `fix/security-zip-minimal-deflate-20261018` | #2793 | fix(zip): reconcile Cargo.lock after minimal-deflate dependency removal |
| [#2821](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2821) | closed | true | `d3ab4f1f37b5f5a2323022ff6988391d76ca187e` | `fix/neuron-final-use-effect-inventory-20261018` | — | ci(neuron): B4 closed-world claim + guarded-effect callers and manifest trigger |
| [#2822](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2822) | open | true | `f1b128f888f021591fdb11b94e28cf467633d70f` | `fix/security-keyring-secret-service-sync-20261018` | #2784 | fix(linux): vendor libdbus for sync keyring backend |
| [#2823](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2823) | open | true | `35edda311360c60aab3ca7454ba036f2896f7392` | `maintenance/security-cargo-lock-toml-header-20261018` | #2817 | fix(ci): force complete V8 canary if historical merge-base Cargo.lock is invalid |
| [#2824](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2824) | open | true | `faa3d1cbd0cd7d64da6f4a7b228daee99a4df29d` | `fix/scope-wal-nofollow-20261018` | #2788 | style(control): apply hosted Rustfmt to symlink-safe Scope WAL hardening |
| [#2825](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2825) | open | true | `859b5e8d717b3f87e135b0f77043bb12d1881e4e` | `main` | — | [DRAFT] fix(cli): bound Rust 1.95 native-impact async query-depth overflow |
| [#2826](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2826) | open | true | `21eeda36754b523461464a423acfc0c5f6388a01` | `fix/security-keyring-vendored-dbus-exact-20261018` | #2822 | security (draft): remove async zbus4 keyring dependency in MCP OAuth |
| [#2827](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2827) | open | true | `7fd4b93c6fd917ad5e07115a6b2a929ea62b8964` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | fix(ci): close strict Fleet authority fixture Clippy on shared Encoder |
| [#2828](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2828) | open | true | `b9028ae8674ec7a5eb68b62a7e48a2c1d0f6deea` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | fix(control): Windows WAL torn-tail recovery requires truncate-capable handle |
| [#2829](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2829) | open | true | `3f23b5e4c84003dd7b5c894a35156ffe5bf8ba03` | `fix/security-zip-lock-reconcile-20261018` | #2820 | security integration (draft): ZIP Cargo.lock plus vendored sync keyrings |
| [#2830](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2830) | closed | true | `4deca7096fd202cd6f1d0fc074f5fe7a2e80ca8e` | `fix/security-zip-20261017-v4` | #2717 | [DRAFT][P0][DENY_ALL] Remove invalid Cargo.lock first line from security branch |
| [#2831](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2831) | open | true | `3283953a4e9f9b26c161482124b6f09e583112e4` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | security: bring reviewed rustls 0.23.46 RustSec fix onto shared Encoder |
| [#2832](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2832) | open | true | `098ce9fefe8f06d3972b97a47b697b0732582b03` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | fix(neuron): length-bind v2 reference output evidence (request/model ambiguity) |
| [#2833](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2833) | closed | true | `b844e35fa04a1f4ed33c80d6595a2c354277d0af` | `fix/cell-split-signed-observer-20261018` | #2766 | test(fleet): close strict Clippy unwrap fixtures for signed observer CI |
| [#2834](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2834) | open | true | `6c8d293aaebd379d77d2bdf2448b838378263459` | `codex/p4-cell-64case-gpu-wal-20261018` | #2759 | test(p4): distinguish low-order observer key from forged signature |
| [#2835](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2835) | open | true | `1de8c3f6f6fbac0c5a3060bbbe1541e270285480` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | fix(windows): match v8-poc sandbox crate feature to linked V8 |
| [#2836](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2836) | open | true | `e49fa304adfa90559981ac4eb0f4f62a2439965e` | `feat/neuron-final-use-production-gate-20261018` | #2757 | fix(final-use): close guarded-effect caller proof for neuron and microbatch |
| [#2837](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2837) | open | true | `9713fd7932501488b68ad2c1f72fef3d364ab7f7` | `main` | — | test(fleet): remove strict-Clippy unwrap fixtures without production changes |
| [#2838](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2838) | open | true | `fcb129645ba9660e394dc57b4baa1089dce6dc4a` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | [DRAFT][DENY_ALL] Integrate actual P0 CI fixes with strong 64-case Cell matrix |
| [#2839](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2839) | open | true | `7c84a70af31fea7f52e7a879c751a19bab0633fb` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | ci(bazel): preserve failing Windows test.log when console output is truncated |
| [#2840](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2840) | open | true | `6d255730e083e754081044a8a2ed85dcffb1c946` | `codex/ci-2753-windows-sqlite-schema-oracle-20261018` | #2805 | [DRAFT][CI] Requalify native codex-cli query-depth fix on #2805 exact HEAD |
| [#2841](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2841) | open | true | `7ae2a5959a8aa1ea47672a301f5119299d780435` | `fix/windows-scope-lane-wal-torn-tail-permission-20261018` | #2828 | style(control): close exact Windows WAL rustfmt gate after 6/6 recovery tests |
| [#2842](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2842) | open | true | `83824134fc3b4e21ef3bcb5bcfa3bb5dcd0d8b6b` | `codex/group-ndu-deterministic-20261017` | #2695 | [DRAFT][CI] Restore Cargo rename aliases in Bazel Rust rules |
| [#2843](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2843) | open | true | `83c657ba5bdeade4bfdf6e752460b2e470060aad` | `research/real-reader-intake-p4-20261017` | #2714 | [DRAFT][CI] Rerun identical macOS Bazel job once after JVM exit 37 |
| [#2844](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2844) | open | true | `5fb6c1acc0d59f758faad0ab20dc5dd6884ddc00` | `shared-encoder-blocker-closure-rerun-20261018` | #2734 | DRAFT: route Automation migration history fixture through canonical SQLite shim |
| [#2845](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2845) | open | true | `60eb1a36e4e59291698a9652e9d5276d957f6678` | `codex/sngr-fbsde-shadow-20261017` | #2611 | test(evidence): distinguish global outbox cap from per-issuer cap (Windows CI) |
| [#2846](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2846) | open | true | `dcd8c9a32ddc458c67adaabe35c2fe24199d1f51` | `integration/p4-64case-security-reports-latest-wal-20261018` | #2798 | fix(p4): deny unsigned observer extensions and unknown matrix report fields |

## Remaining audit limits and next actions

- Repository changed during reads. Re-fetch head/base/state/checks immediately before mutations.
- Branches/PR pagination complete for observed collection, but absence of duplicates cannot prove absence of branch insertion/deletion races.
- Authors and assignees do not establish a unique live development Agent owner.
- Base-ref edges are verified metadata; body #mentions are not verified dependencies. No arbitrary semantic superiority or obsolescence judgment.
- Not all 2846 diffs, reviews, historical workflow jobs, or scientific receipts were audited by this subtask. CI owner supplies separate matrices.
- Closed/unmerged does not establish obsolete, unsafe, duplicate, or superseded semantics.
- Temporary/research categories are provisional and cannot authorize deletion, merge, or production promotion.

Read `pr_inventory.json`, `branch_inventory.json` and `branch_pr_edges.json` for all machine-readable rows; `ALL_PR_TABLE.md` contains the complete PR table. Compare semantic patches and freshly joined exact-head CI before choosing any integration owner, closing temporary carriers, or approving a merge. Research/Shadow candidates keep their current fail-closed boundary.

## Exact captured branch SHA ancestry closure

All **2,519 captured branch SHAs** now have actual commit-graph comparison to frozen main `f8c9419df6ddeb36ff8b522a50219981fb8d9345`: 2,463 use read-only local Git objects; the remaining 56 branch names (50 unique heads) use authenticated GitHub commit comparisons. Missing local objects were not reported as absent remote branches.

| Graph relationship to frozen main | Branches |
|---|---:|
| Same commit graph as main | 2 |
| Contains main, with additional commits | 289 |
| Ancestor of main, no unique commits | 28 |
| Both sides have unique commits | 2200 |

These relations alone do not establish patch equivalence, semantic superiority, deployment safety, or permission to discard a branch. `branch_inventory_enriched.json` contains every graph row and method; `remote_missing_branch_comparisons.json` retains GitHub per-file stats. Any remote compare file list at the API cap is flagged rather than asserted complete.

## Open-PR graph validation and PON donor review

The 1,553 open PR metadata nodes have 1,250 actual base-ref parent edges, no directed cycle, and no ambiguous multiple open-PR parent match in this collection. This verifies graph structure; it does not verify that stacked heads contain current parent code. See `pr_base_graph_validation.json`.

Exact comparisons confirm that #1500 and #1501 are closed without merge, while #1504 remains open/Draft. Relative to #1501, #1504 changes three paths: the Bazel shell wrapper, its new failure-preservation regression suite, and the native-pair workflow. The workflow changes exact Chain source/prospective-merge pins, whose scientific/security suitability is not established here.

The existing four wrapper tests from #1504 passed against its exact wrapper, with every source blob hash checked. Against the older #1501 wrapper, the same tests produced two passes and two failures: a failed tee capture returned success (0 rather than 23), and a failing diagnostic tail replaced the primary Bazel failure (29 rather than 37). These are shell-wrapper unit tests with recording/fault-injection probes, not real Windows, Bazel, PoN, or model qualification. The before/after receipts are `pon_wrapper_baseline_failure_receipt.json` and `pon_wrapper_unit_receipt.json`.

The only additional Rust change in #1500 versus #1504 is the Windows owner-root canonicalization in `migration_convergence_tests.rs::reopen_persisted_history`. #1504 has not absorbed it. The donor uses a further `.expect()` in a helper, so preserving the normalization intent still requires strict lint qualification or proper typed error propagation; blindly copying the donor is not closure. Both scoped patches are retained.
