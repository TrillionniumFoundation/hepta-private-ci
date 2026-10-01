# ui.native ordinary-source review map

The current review base is `9be52d267d02a76f73e8a94fd086191c351d1c70` on
`work/ui-native-qualified-integration-20260928`. The audit branch is
`work/ui-native-adversarial-audit-20261001`. Read CURRENT_SOURCE.json for the
immutable implementation SHA/tree and ADVERSARIAL-AUDIT-20261001.md for findings.

The current implementation source for this follow-up is
`703e9bf2871b26d646f1c4d748e0b0061f70ad3c`, tree
`d549e3e492093810b685c7d65d58d6983566a82b`. This ordinary commit changes three
fixture files: actual Unix zero-exit candidate copy, environment-only picker
Command, and Windows authority helper error propagation. It retains startup
rejection, rollback digest/mode assertions, owner lifetime and strict lints.
The inventory selection remains 406 Git blobs, 32 paths and 16 local Cargo
dependencies, inventory SHA256
`485b4790cdbb806fc51653d280ff4f7b690bff35e95ba4301ce653fd339f7091`.
The re-anchored precommit structural checker passed for this exact 406/32/16
inventory. This is a structural diagnostic, not platform or release acceptance.
CURRENT_SOURCE.json binds this new inventory. Full current
suites, strict lint, owner, full-symbol ACK, release, storage/performance and
same-run CI are pending.

The focused Linux 2/2 pass (0.163 s) was observed on the post-EBD worktree whose
three repaired files match 703e9bf blobs; it is not a full suite or macOS/Windows
execution. A standalone Rust 1.95 type-shape Clippy probe exited 0: complexity
230 is below 250. It does not qualify the Windows fixture.

Historical EBD source `ebd04a7ed458aa5feaba69525f48f3623c4db033` repaired 11
source files covering checkout attributes/identity, macOS cfg/FIFO and Windows
registrar ABI/PATH/owned-shortcut coverage. Its Linux debug 243/243, Python
238 total (237 passed/one Windows junction skip), map 104/104, package/portal
36/36, projection seven tests, strict application Clippy and full-symbol ACK
1/1 are archived in
[`history/20261001-ebd04-verification.json`](history/20261001-ebd04-verification.json).
Run 36822033441 failed overall: identity, Linux head/merge (18 checks each,
including virtual GUI lifecycle) and storage (48 traces/all hard budgets)
succeeded; macOS full tests, Windows owner lint and aggregate failed. See its
[Linux child record](history/20261001-ebd04-linux-verification.json).
macOS full application tests failed on absent `/bin/true`; Windows owner lint
failed on five helper `unwrap` calls. Those failures motivated 703e9bf and
supersede the prior bounded-review stop. EBD passes do not qualify this freeze.

Earlier source `0c176c9d4df6055418529389bf0f749f74ac1a69` passed local normal debug
243/243, Python 236 total (235 pass/one Windows junction skip), combined map
104/104, package/portal 36/36, projection seven tests, strict application Clippy
and the full-symbol ACK fixture. These source-specific diagnostics and real
run 36820183453 are preserved in
[`history/20261001-0c176-verification.json`](history/20261001-0c176-verification.json).
That run passed Linux head/merge and storage with 48 traces/all hard budgets,
but failed macOS strict
compilation and one Windows Python command fixture. Its passes are historical
and cannot qualify ebd04. The further real autocrlf checkout challenge reproduced
18,697 CRLF lock lines; the current source pins LF and retains exact byte checks.

The old 32310 local release counts, measurements and partial real CI storage
results are immutable history in
[`history/20261001-32310-verification.json`](history/20261001-32310-verification.json).
Run 36796737020 failed overall despite successful Linux merge and storage
subjects; Linux head ACK and macOS/Windows Python failed. Its prior queued
status and the older static-review convergence conclusion are superseded.
Historical evidence is not relabeled as a pass for this source; a Windows-only
test skipped on Linux is not Windows execution.

Historical WAL/index, portal, paging and package commits remain ancestry. The
old `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52` freeze and
`6f145464d9d58233c59aafe262a1250a5ea873a8` review base describe earlier work.

| Audit source change | Commit |
| --- | --- |
| fence sessions and bound presentation input and diagnostics | `f8c078f8006a1e824a428540f7b63b27e2f1cb9c` |
| pin private journal roots and repair durable recovery boundaries | `befe5c710291cf3374859535c57687cd31b1206e` |
| bind update copies and arbitrate confirmation and rollback | `12fc86051bcb189fc21171eff9c33533fa914052` |
| align regression fixtures and enforce strict lint | `0d8afb30f7a2d68125eb7d6f2be4eb771d82ff81` |
| fence watchdog failures with durable update ownership | `4e307a0e69cf24b82457a636091b81fce9115a73` |
| bind complete source and dependency evidence and measure real storage samples | `f4ce125546ab743ebedbc793762add89b1143ac3` |
| keep semantic storage ceilings immutable after source freeze | `9dcb16b980c22dee2c215e9fb116fcf99248a77a` |
| share Windows private state without product dependency cycles | `f93cf2913868aeef4ad2e2496804f459d47e3a46` |
| reconcile retirement in bounded validated prefix batches | `dbde0b4fc00b1d9bdc434dcd78cee30d0823fafd` |
| qualify combined storage using the product release profile | `d6502257d890b915d2287cfc188509d8f18bdd6b` |
| bind WAL regression imports to the journal owner | `21cbe83cf85994bcbfd29666b5acd9d82cc15294` |
| rebuild mixed retirement histories with bounded authenticated spools; bind real first-migration samples and qualification boundaries | `ed5fd2229502099addd6bedec2fae18783d5c162` |
| validate private child capabilities and keep mutable files single-linked | `f1d5eff58fffe8fba355f9ec94b9aa050d6ec33e` |
| prepare bindings on the supervised worker and discard stale input/view projections | `8cec5eba730f07e128b8b8d925a0f6acf9b6001d` |
| bind update persistence, lock contention and staged copies to retained roots | `4355faf5ceddb91a2e571f3448f062038f921e8f` |
| retain updater activation ownership and admit only one exact staged package | `768f53e42c17c0983587175c6f693ad30f7bad71` |
| regress namespace replacement, failed stage publication and rooted startup records | `9f1bcbdc28c9f48f55266528dd030cd3cde20ca7` |
| bound Windows notification identity and compile the packaged registrar source | `ca66da671da6f22f1fe8e4ff4ddb4c8fdb8cf7b3` |
| use a fixed oversize marker fixture under strict native lint | `32310eefbef2a80164b669fe3bfcaef69b47b9da` |
| preserve fail-closed dependency identity under root aliases/reparse points, LF metadata and explicit Git for Windows Bash; separate ACK fixture phases | `85185bcb274682ece9da5086813fd60cc2a7214a` |
| optimize SHA-256 only in the test profile while hashing full executable symbols and preserving production update fences | `0c176c9d4df6055418529389bf0f749f74ac1a69` |
| freeze checkout attributes and owner-lock LF; regress real autocrlf checkout and owned fixture command selection; fix macOS cfg/Unix FIFO and Windows PROPVARIANT layout/owned-shortcut roundtrip | `ebd04a7ed458aa5feaba69525f48f3623c4db033` |
| use the actual Unix zero-exit executable and propagate Windows authority fixture errors while preserving strict checks | `703e9bf2871b26d646f1c4d748e0b0061f70ad3c` |

Later review commits update validators, source anchors, technical/development
documentation and evidence navigation. Product edits require a new freeze;
semantic storage budgets remain frozen except the two source-anchor fields.
The checker derives the full local Cargo dependency closure. Qualification
tooling is reviewed at the exact candidate/workflow identity.

Review commands:

```bash
implementation="$(python3 -c 'import json; print(json.load(open("apps/hepta-native/CURRENT_SOURCE.json"))["implementationSourceSha"])')"
git diff --stat 9be52d267d02a76f73e8a94fd086191c351d1c70.."$implementation"
git diff 9be52d267d02a76f73e8a94fd086191c351d1c70.."$implementation" -- apps/hepta-native/src
python3 scripts/check_hepta_ui_native_convergence.py
```

Review directory-handle ownership and WAL/checkpoint recovery first; then update
child-root ownership, same-handle Windows ACL checks, mutable hardlink rejection,
copy digests, rollback identity, ACK/cancellation arbitration and bounded staging
admission. Trace helper activation through its existing manager root and binding
preparation through exact input/view capture, worker admission and stale-result
discard. Inspect the headless egui projection and packaged C# compile regression
within their stated test scopes. Finally inspect exact source/package/SBOM semantics, raw performance
samples, durability counts and the seven-subject evidence aggregate. Review the
new root-alias and actual Windows junction fixtures, LF/Git-byte drift rejection,
explicit Git Bash selection and separate readiness/exit deadlines. Confirm that
the test-only `sha2` optimization does not strip the subject or alter production
5/35-second deadlines, complete digest checks or update-owner fencing. Check the
frozen attributes against real autocrlf checkout and immutable lock digests.
Inspect Linux-only cfg while retaining all-platform root validation, real Unix
FIFO rejection, and Windows PROPVARIANT native size/offsets plus owned `.lnk`
property-store roundtrip; their source presence is not a real macOS/Windows pass.

Independent review of the three latest fixture repairs found no further
reproducible issue within that scope; fresh full suites and CI remain pending.
The earlier EBD static-review stop was superseded by executed macOS/Windows
failures. New execution failures require another ordinary source repair and
freeze. The result remains an incomplete implementation candidate. Non-Linux verified
Open/Reveal adapters remain absent. Physical acceptance, coverage, soak,
production signing, independent supply-chain acceptance and release authority
remain explicit gates.
