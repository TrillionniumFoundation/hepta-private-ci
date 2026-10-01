# ui.native ordinary-source review map

The current review base is `9be52d267d02a76f73e8a94fd086191c351d1c70` on
`work/ui-native-qualified-integration-20260928`. The audit branch is
`work/ui-native-adversarial-audit-20261001`. Read CURRENT_SOURCE.json for the
immutable implementation SHA/tree and ADVERSARIAL-AUDIT-20261001.md for findings.

The current ordinary implementation source is `0a129b41c2a2d42ca907ea8257bf780108bc664f`, tree
`f90313f067446c629b8da50058ee1bd2101e76e7`.

Native update owner, handoff and runner locks now return an opaque
`updater::UpdateLock` instead of exposing a File. Successful acquisition builds
one lifetime guard; dropping it explicitly unlocks before closing the handle,
including a failed post-acquisition root check. Failed acquisition never
unlocks another owner. Retain the runner guard for the existing orchestration
scope. Final-use and authority-lease stores also unlock on their last owner
Drop, including failed trust construction; Arc/token ownership remains intact.
No retry, test serialization, deadline change or new authority was introduced.

Windows private atomic snapshot/copy publication now validates
the existing destination and same temporary descriptor before private bytes and
before commit. Private-source copies recheck their retained source descriptor;
external installer inputs/targets keep their own policy. The shared Windows
utility validates staging and existing destinations before replacement, then
closes its non-delete-sharing verifier handles before the actual rename.
Checks reject unsafe evidence without repairing its ACL or replacing its bytes.

The cancelled-ACK fixture accepts BrokenPipe only after durable cancellation;
successful ACK delivery, candidate exit, rollback and predecessor-byte assertions
remain enforced. Qualification merge construction and reconstruction now send
fixed UTF-8 LF bytes to Git, producing the same ordered-parent commit on every
OS. The strict source/tree/parent/workflow/run/attempt checks remain unchanged.
Darwin same-descriptor ACL/ownership, Unix NONBLOCK admission, typed Windows
registrar and the three macOS baseline fixture corrections are retained.

CURRENT_SOURCE.json binds 420 Git blobs, 32 selection paths and 16 local Cargo
dependencies, inventory SHA256 `8865ed312eaff178ad8909e2e1fadb3a53ec009fe8297f5e09692afb4c3b58e6`. Production, deployment
and release flags remain false. Fifteen Windows atomic/ACL regressions remain in the new-source target suite;
passing D544 executions are historical evidence only.

Precommit Linux diagnostics for the lock repair passed application 245/245
(2.460 s; three independent scale entries ignored) and strict all-target/all-feature
Clippy (8.67 s). The exact-copy reduced contracts workspace passed focused 2/2
and full all-feature 196/196 (1.028 s), scoped fix and strict Clippy. These are
local diagnostics, not immutable-candidate qualification; the standard owner
workspace's offline metadata attempt stopped on an unrelated uncached imbl
package. The public UpdateManager runner API also passed a controlled fork
red/green with the same harness. Current qualification-tooling Python passed 239/240 in 15.191 s (one Windows
NTFS-only skip). Three locked/offline release binaries built in 23.09 s; binary
self-test and seven actual child-fault checks passed locally, with all effect,
activation and release authority false. A new complete same-run current-source
platform/storage run and packaged-artifact evidence remain required.
This is the publication-time metadata capture, before the final workflow completes.
The current exact-run receipts are attached to [draft PR #1308](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1308).
The separately committed navigation guard and owner-guide precision repairs are
`9ca0e42e211e87cf3fd0d1a15ba9d484d20093a9`, tree
`9fa335e95a577c642683252b00d7f6d23708f5d7`; these scripts and guides are outside
the frozen native product closure. CI still binds the complete candidate commit.

Historical D544 candidate632d/run36838749224 completed FAILURE. All three
actual merge subjects matched canonical LF SHA7d22e1fa3576681ae721fe3effb4a30f6806ec2a.
Linux head (243 application/212 owner), macOS head (254/230), both Windows
subjects (209/173, including all fifteen named atomic/ACL regressions) and all
48 storage traces/hard budgets passed. Linux merge failed on update-lock
contention; macOS merge failed the legacy fixture's precise InvalidTrust
assertion, without printing its actual variant. Aggregate correctly stopped at
the failed-subject gate; deep aggregation and acceptance did not run.

Controlled same-Rust flock/fork, public UpdateManager API and actual Store
alias experiments reproduce the close-only lock lifetime defect. Explicit
unlock passes while inherited descriptors remain open and preserves the
successor's lock. These experiments prove a fixable mechanism and API defect;
the precise original CI scheduling cause remains unproved
(actualCiCauseProven=false). The original eighteen metadata fields, exact
platform children and later terminal observation are retained in
[632d historical record](history/20261001-d544-632d-verification.json); no pass is inherited by this new source.

Historical candidate dc59/run36836809639 completed FAILURE: immutable identity
and storage succeeded, both macOS subjects failed shell parsing before checks,
and Linux/Windows correctly rejected productExecutionComplete=0 but failed the
fixture's stale error-message expectation. Both Linux and Windows merge subjects
actually matched
658914a3e602337e707901a9f8d11388b6486799; no Mac merge or Rust/ACL pass was observed.
The producer now defines its Python heredoc in a standalone shell function,
outside quoted command substitution, preserving fixed binary LF and every
identity check. The regression executes head and merge with Python single/double
quotes and an apostrophe comment, using native /bin/bash on macOS. The malformed
bool fixture now requires its precise rejection diagnostic; input0 and denial
remain. Forty-eight targeted regressions passed locally. Actual new-platform
execution is required. See [dc59 historical failure](history/20261001-dc59-verification.json); its original 18
localAudit fields and independently captured platform children remain unchanged.

Historical source89/candidate8c/run36832001532 actually passed all seven producer
subjects: both Linux/Windows/macOS head and merge suites plus 48 storage traces
and unchanged hard budgets. Each macOS subject executed all 32 ACL and both
Unix FIFO cases. Aggregate nevertheless failed: the Windows merge's CRLF commit
message produced b09d1a4b409537432dec6b8876e4e63843b5cd0c instead of canonical
LF merge6a3cd7ea61a6e718c1065d323ec7022b9b3d68bd, with identical tree and ordered
parents. Exact Git bytes prove the difference. This is an executable identity
defect, not a physical-host gate. Old tests also omitted the newly repaired
Windows atomic-publication calls. See [20261001-89c64-verification.json](history/20261001-89c64-verification.json); its original
18 localAudit fields and all three platform children remain historical only.

Intermediate source403's local suite passed242/failed1: the cancelled child had
already exited when the parent incorrectly unwrapped BrokenPipe. Its failed
raw log is preserved in 20261001-403df-verification.json. SourceEE6 repaired that
fixture and passed243; 20261001-ee6a1-verification.json retains those diagnostics
separately. Neither source had a completed metadata review workflow and their
results cannot qualify this new source.

Eleven affected shared-owner maps refresh complete current source observations
after the shared Cargo/contracts/utility changes. Historical sourceBase, operation
states, tests, delegates, callers, receipts and execution/acceptance/activation/
release claims remain unchanged. Navigation does not establish product execution.
The migration guard explicitly recognizes module-specific executable, host and
release qualification fields, requires actual bool values, and rejects stale
execution proof before metadata writes. Source and structural completion facts
remain distinct. Two pre-existing NDU source drifts remain whole-project blockers;
this work preserves their historical claims rather than rebinding those receipts.

Historical B537 source `b5378e29d0fe191225abe853d848b498552f5850` in candidate58/run36830035079
passed both earlier corrected fixtures, library 145/145 and all 14 native ACL
cases on macOS. Its full application suite then failed retirement recovery
because a fixture newly created head.json with default 0644 mode; each subject
had 208 passes/one failure/three ignored. Shared-owner ACL/FIFO, release and
package stages were not reached. Exact old localAudit fields and separate
actual raw failures are retained in [20261001-b5378-verification.json](history/20261001-b5378-verification.json); no
historical pass or pending field is relabeled as current qualification.

Historical A1 source `a1abe5b2a083213c095cdabaf4b3048144e3cad0` passed Linux application 243/243,
Python 237/238 with one Windows-only junction skip and isolated owner 194/194.
Its F5 run 36827460737 actually passed strict macOS lint and all 14 native ACL
fixtures, but both application suites failed two older fixture assumptions.
Shared-owner ACL/FIFO cases were not reached after application failure. The
failure and local diagnostics are retained in [20261001-a1abe-verification.json](history/20261001-a1abe-verification.json);
the distinct F5 and 8f CI candidates remain separate, and pending subjects are
not passes. This actual failure supersedes the prior review stop.

Historical source `703e9bf2871b26d646f1c4d748e0b0061f70ad3c` has fresh clean-review-head Linux diagnostics:
application 243/243 (three separate scale entries ignored, 4.803 s), Python 238
total (237 passed/one Windows junction skip, 14.970 s), strict application
Clippy (7.51 s), three actual external E0603 boundaries, three release binaries,
self-test and real child-fault recovery. Run 36823756631 passed both macOS
subjects and Linux storage; both Windows subjects failed their registrar
fixture because PowerShell marshaled `System.RuntimeType` as an object.
Its exact receipts and terminal status are retained in
[20261001-703e9-verification.json](history/20261001-703e9-verification.json). The subsequent independent Darwin ACL/FIFO
review and Windows failure require this new freeze.

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
| call the typed Windows registrar size probe; retain native offsets and owned shortcut roundtrip | `d18f3bb937980d182aa9969fde78f9f258b1117f` |
| add the Darwin same-descriptor ACL/ownership utility, six actual ACL fixtures and required Cargo edges/locks | `4bb12103b9ae141bf0a416345ab6e89c8d0b9101` |
| check native roots/children, private files, staged sources and atomic temp/existing destinations; add 14 Darwin fixtures | `bd552fb3e9ed0e52b691650d75053ede1001e91d` |
| reject unsafe Darwin final-use state/claims and Unix authority FIFO reads; retain root and staging descriptors | `9491cf79e7b94e852b16bdbe30ab0943be673fb2` |
| apply equivalent authority lease cuts and bounded FIFO rejection; freeze the complete five-stage source | `a1abe5b2a083213c095cdabaf4b3048144e3cad0` |
| align Darwin root-replacement expectations and private staging permissions; require every injected replacement cut to execute | `b5378e29d0fe191225abe853d848b498552f5850` |
| create the retirement-failure baseline privately and assert owner-only mode before the intended record conflict | `89c64152c9b971fcaabe98aeb0d24452e1c6e30d` |
| validate Windows private atomic temporaries, old destinations and held copy sources; preserve unsafe evidence | `403df62a7bf3ac065f2b0ad21661d08b66b32731` |
| admit a closed late-ACK pipe only after durable cancellation; preserve every rollback assertion | `ee6a155661ad7e051a25d90eb5cc37ca1ce5d5b4` |
| use fixed LF bytes for cross-OS deterministic merge identity; retain strict validation and refresh shared-owner guide precision | `d5445993e9ac96626bf9314053df77eeedb90e4d` |
| Explicitly release scoped update and authority-store locks; preserve successor and trust rejection | `0a129b41c2a2d42ca907ea8257bf780108bc664f` |

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
child-root ownership, same-handle Windows and Darwin ACL checks, ignored-ownership rejection, existing-destination preservation, nonblocking authority-file admission, mutable hardlink rejection,
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

The earlier bounded review stop was superseded by actual Windows fixture
failure and the independent Darwin ACL/FIFO findings. Re-review the new cuts,
then execute the exact frozen source on every target; fixture source and partial
historical success cannot establish convergence or platform acceptance. The
result remains an incomplete implementation candidate. Non-Linux verified
Open/Reveal adapters remain absent. Physical acceptance, ownership-ignored
volumes, coverage, soak, production signing, independent supply-chain acceptance
and release authority remain explicit gates.
