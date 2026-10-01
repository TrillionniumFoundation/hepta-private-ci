# learning.operator adversarial audit — 2026-10-01

## Scope and source

Base: `997e7beef8151160065df36b024bc8da5c989e93` on repository `main`.
The reviewed source is `codex-rs/hepta-bellman-operator`, with explicit
cross-owner integration scope limited to Agentd cognitive ranking and control
publication, the existing learning-ledger publication contract, the shared Replay
terminal adapter and their regression fixtures. No durable writer or selection authority is
introduced. The candidate branch and Git commits identify the delivered revision;
this report does not attempt a self-referential current-commit hash.

Reviewed documentation: `docs/DEVELOPMENT.md`, module `TECHNICAL.md` and
`IMPLEMENTATION_MAP.json`, readiness learning/source specifications,
`HOLDER_BELLMAN_SPEC.md`, the module execution dossier and `NATIVE_MAPPING.md`.
Detailed technical development documentation exists. Its main weakness was
inconsistent descriptions of implemented reference arithmetic, future simulator
work, finite-design geometry and already existing explicit consumers.

## Reproduced defects and remediation

| Finding | Before | Delivered behavior |
|---|---|---|
| Sensor design collision | Unselected candidate coordinates could change while retaining selected points and geometry | Canonical complete candidate point semantics bind the V2 manifest digest preimage; the native record remains V1 |
| Reference evidence collision | Different cell evidence or reward/continuation decomposition could retain the same receipt | Canonical complete cell inputs and evidence bind the receipt |
| World-model evidence collision | Reassigning underlying observations while preserving aggregates retained the model identity | Each observation's complete semantics bind the estimate; retained model statistics bind a recomputed V2 digest |
| Unbound support policy | Changing minimum samples could retain the fitted artifact identity | The admission threshold binds the candidate digest |
| Public mutable prediction bypass | Invalid tabular grids/statistics/authority or world-model distributions could reach prediction | Tabular predictors share bounded structure validation; world prediction validates counts, distributions and retained digest |
| Impossible loaded statistics | A single sample could have distinct extrema, or two samples an incompatible mean | Encoder and pinned loader enforce nearest-even attainable mean intervals with overflow-safe arithmetic |
| Repeated cell evidence | Distinct canonical cells could claim the same retained evidence digest | Encoder, loader and mutable prediction reject duplicate cell evidence |
| Dataset verification duplicate collapse | A set hid repeated evidence while issuing a verified token | Row cardinality and exact canonical membership must agree |
| Early resource work | Strict fitting collected/sorted evidence before the bounded fitter; world dataset verification processed oversize inputs | Limits run before that extra work; redundant evidence sorting is removed |
| Incomplete signed budget | Signed qualification accepted a partial error-component set | All seven evidenced components are mandatory; missing/unknown components reject |
| Owner-context drift | A self-consistent receipt could carry another scope/epoch, future frontier or invalid terminal metadata | Bounded owner context, head/frontier and watermark checks precede target derivation |
| Frozen-input trust/time drift | Frozen inputs could cross owner trust rotation or reversed time | Opaque terminal input binds trust identity and admission time, rechecked before fit |
| Scheduled freeze revocation/expiry | Fit accepted an expired or scheduled-revoked freeze attestation even though its trust digest was unchanged | Signed V2 inputs retain the original attestation and exact payload; fit re-verifies them at current time without substituting a later head |
| Unsigned freeze provenance | A V3 receipt alone cannot authenticate historical freeze issuance | Additive signed-owner V2 invokes the actual LedgerWriter signature verification and owner-derived freeze |
| Registry/payload producer mismatch | Cognitive ranker checked artifact ID but not producer | Both immutable artifact identity and producer must match the selected registry manifest |
| Numerical inconsistency | Target discount multiplication used half-away while the reference used nearest-even | Positive and negative half ties follow the canonical nearest-even profile |
| Truncated terminal diagnostics | Two terminal rows out of three rounded downward by one LSB | The terminal fraction uses nearest-even conversion, including zero/full endpoints |
| OOD boundary false rejection | A legal representable rate strictly below 0.5% was rejected | Exact rational comparison permits raw 21474836 and rejects raw 21474837 |
| Inconsistent golden vector | Published target differences and gaps disagreed, and no six-cell native test exercised the vector | HBO-GV-001 freezes separately quantized reward/continuation arithmetic, checks all six targets and three gaps, and verifies canonical permutation |
| Native/wire conformance overclaim | Owner-local Rust records were described as equivalent to canonical JSON contracts without an adapter or conformance tests | The canonical wire adapter remains explicit repository implementation work; V1 compatibility and signed V2 admission guarantees are distinguished |
| Signed ingress without consumer wiring | Signed owner freeze was available only as a lower-level API/test path | The shared Replay host exposes additive signed-owner training and retains the same signed Frozen through its common source-bound fit path |
| Underreported geometry | Integer square root/division could understate coverage or mesh ratio | Fill/mesh round upward and separation downward |
| Avoidable quadratic work | Coordinate deduplication compared every candidate pair; separation repeated pair distances | Ordered coordinate set and existing farthest-point nearest distances remove those passes |
| Excess digest buffering | Long sample identifiers could accumulate hundreds of MiB of extra digest input | Canonical per-row hashes retain every semantic field with approximately 32 MiB maximum sequence buffering |
| Non-ancestral documentation anchors | Historical map commits were outside the current main ancestry and could not be migrated by the strict verifier | Reviewed operator/direct-dependency navigation is explicitly rebound; original provenance remains recorded and no historical execution claim is renewed |
| Missing artifact protocol definition | Contracts and algorithm prose named `BellmanOperatorArtifactV1`, but the canonical schema registry omitted it | All 14 design fields, bounded encoding and critical-field policy are registered; the algorithm requires this protocol |
| Public-digest final-use forgery | A real SQLite/ranker consumer accepted swapped result order after the caller recomputed the public evaluated-context digest and retained the genuine plan receipt | Private process/body issuance binds the complete ordered response and original monotonic deadline |
| Unbounded final-use envelope | Current owner rows could be supplied with a self-consistent digest despite exceeding the delivery byte budget | Bounded borrowed serialization checks the complete four-item/8 KiB envelope before hashing, including escaping and plan fields |
| Withdrawal during awaited providers | A source withdrawn after acquiring the owner cut could remain accepted while a CURRENT provider was awaited | The actual owner cut is revalidated after provider awaits, adjacent to read/final-use return |
| Learning append before issuance failure | A response rejected by the new capacity or deadline checks could already have appended learning delivery evidence | Delivery is deferred until the final host fence and successful issuance; failed publication retracts the private issuance |
| Duplicate issuance interference | Two attempts could share a live receipt; failure of one retracted the other successful attempt | A live receipt cannot be issued a second time, and rejection leaves the original record intact |
| CURRENT drift during deferred publication | Moving delivery append beyond the earlier CURRENT check left a new unchecked publication window | Real owner/issuer/ranker/retrieval revalidation surrounds deferred ledger I/O |
| Claimed index absent from consumer | The guide described indexed owner admission, but two candidate passes still scanned every admitted record | Both passes share one borrowed record-ID index and retain the original live/revision/hash/scope checks |
| Empty model application | Empty candidate batches were labelled learned-policy applied even for unseen queries | Empty batches abstain after CURRENT verification; metadata no longer attributes a nonexistent ranking |
| Late admission cost | Invalid native grid/sample sizes reached receipt verification; impossible loaded sample/sensor/action totals were rejected only after full collection | Shared scalar bounds precede dataset verification; single-pass loaded validation rejects limits immediately |
| Protocol field drift | Deleting rollback or changing required/type semantics could pass generic schema checks | Generic design-field declarations enforce all 14 fields through algorithm and global verifiers, with mutation regressions |
| False late exposure | A late lifecycle/CURRENT/deadline/transport failure could leave a durable true exposure assertion | The production transport writes intent before bytes and confirms only a complete host write; legacy assertions remain legacy |
| Reused client correlation ID | Independent clients restart request IDs, causing durable identity conflicts | V2 identity binds the complete canonical intent, including causal assignment and exact frame, in a new domain |
| Wrong transport frame | A private pending handle could be paired with another frame by an internal caller | Full digest and length are checked before the first write |
| Detached append queue | Connection timeout released its permit while non-cancellable blocking appends could accumulate | A separate 32-slot reservation follows the actual worker and pending confirmation until completion/drop |

The tests cover equal-output/different-input digest changes, canonical permutation,
integer extrema and half ties, malformed mutable artifacts, forged but correctly
pinned payload bytes, duplicate evidence, signed payload/scope/expiry drift,
complete error budgets, real owner corrections/withdrawal, trust rotation and
signed freeze payload/head drift. Repeated independent reviews and a comparison against the previous audit branch
`2f34f3a7d51c39463d8010d5b2c35612cb748319` were performed. That branch
has unrelated cross-version changes and was preserved. Only its relevant sensor
design binding and repeated-cell evidence checks were incorporated. The candidate
uses current main and does not import the old branch wholesale.

## Completion assessment

| Layer | Evidence and remaining boundary |
|---|---|
| Development documentation | Detailed guides, current algorithms/limits/trust tiers and operation/caller mappings; all four Bellman design protocols are registered; design targets remain explicit |
| Native offline baseline | Target arithmetic, sensor design, complete tabular fitting, action-conditioned world model, signed qualification, pinned persistence and owner-derived terminal profile are implemented |
| Explicit integration | Cognitive read consumer and shared replay terminal consumer with signed-owner training exist; neither is a default autonomous learning loop |
| Delivery evidence | Owner-native intent and linked host full-write confirmation use the existing witnessed writer; missing confirmation is Unknown; peer/model attachment and stronger consumer ACK remain separate evidence |
| Canonical wire integration | Native reference records do not implement the full canonical certificate/manifest JSON schema; adapter and conformance coverage remain repository work |
| Default composition | Freeze → train → independent evaluation → selection → new-process load remains repository integration work through existing owners |
| Extended operator profile | Model-backed simulation/interpolation, continuous-domain coverage and optional neural/tensor training require separate implementations and qualification |
| Production and scientific acceptance | Target-host metrics, future-window efficacy, independent science, acceptance, canary and release require external evidence |

The generic dataset-bound V2 token proves self-consistency and exact membership,
not semantic truth of caller-supplied targets, freeze issuance or current revocation.
Its host must perform those owner obligations. The compatible owner V1 path
requires trusted receipt provenance; arbitrary historical cuts/inclusion policy
cannot be authenticated from V3 alone. Signed-owner V2 closes the current freeze
ingress without redefining the receipt wire format. Its original signature and
payload are retained and rechecked at fit even when revocation is scheduled in
an unchanged trust snapshot. A later owner head does not redefine the old cut.

Public mutable tabular artifacts cannot authenticate sample-bound digests from
sufficient statistics. Production consumers use independently pinned immutable
loading. The shared replay adapter's plain registry argument is a host trust
boundary, not independent signed CURRENT evidence. Exact query/revision support
and the 128-action table bound can cause whole-ranking abstention.
The CURRENT provider must independently authenticate the host's authorized
owner/trust configuration and any legitimate rotation; an opaque view is not
proof that an arbitrary verifier configuration is host-authorized. Mutable
admission is O(c log c + c log(s+a)); immutable loaded lookup remains O(log c).

The cognitive consumer's private issuance registry stores no context text and
has at most 256 live receipts. It retains the original plan's monotonic deadline
instead of starting a new TTL after owner/provider I/O. Capacity exhaustion is a
local read rejection and never evicts a still-usable receipt. A new process has
no previous issuance records and requires a fresh read. Duplicate live issuance
rejects without changing the first record. This integrity check is
host-owned ephemeral metadata, not a durable model registry or new authority.
Production learning publication now uses owner-native intent and host-write
confirmation. Preparation/issuance alone writes neither event. After bounded
serialization, intent and its independent witness precede the first success-frame
byte. Actual owner/CURRENT/issuer/lifecycle checks run after the append, and only
complete `write_all` permits confirmation. Partial writes and late pre-write
rejection leave Unknown. Confirmation failures close the connection and disable
subsequent learning-required publication pending safe writer recovery. A private
32-slot reservation bounds blocking work even after connection timeout. Legacy
exposure assertions retain their original meaning and are never upgraded.

Canonical artifact registration defines the full 14-field design contract, not
merely the narrower tabular native payload. Registration verifies field shape,
bounds, all 14 declared design-field semantics and required protocol coverage; it does not implement the JSON adapter,
execute every numeric invariant or establish production/scientific acceptance.

Independent CURRENT providers authenticate their own call-time observations.
They do not offer a common lease or an atomic multi-owner cut. Rechecking before
and after deferred I/O strengthens the existing interface; it cannot promise
that every owner remains unchanged until subsequent use. A stronger guarantee
requires an explicit common epoch/lease protocol, not an unbounded retry loop.

### Delivery protocol and remaining consumer evidence

The staged native protocol is specified in
[`RETRIEVAL_PUBLICATION.md`](../hepta-learning-ledger/RETRIEVAL_PUBLICATION.md).
One intent retains the full causal assignment and planned subset, without an
exposure flag; a separate event links the exact intent ID/event digest and
complete response-frame digest/length. Complete-content identity handles
client-local request-ID reuse and query/policy changes producing the same frame.
Exact retries are idempotent and do not establish physical write counts.

The typed projection exposes LegacyOwnerAsserted, Unknown or
HostTransportWriteCompleted, with separate current-lineage and independent
witness eligibility. A withdrawal cannot erase an already observed historical
write. Generic active source membership or a dataset freeze does not prove
publication. Existing inference/native-started evidence remains necessary for
actual turn/start attachment; neither socket completion nor attachment proves
model token use or causal policy improvement.

A send-to-confirm crash can still leave Unknown even if the peer received bytes.
A blocking confirmation started after a full write may finish after cancellation;
canonical history determines the resulting state. Single-frame IPC cannot make
consumer visibility and fsync atomic. A stronger consumer acknowledgement/gate,
target-host failure qualification and independent learning acceptance remain
separate requirements. Existing tag-9 exposure rows cannot satisfy the new
transport-confirmation contract.

## Compatibility and rollback

Tabular payload layout is unchanged. Retrieval journals add native event tags
10/11; tags 0..9, framing and original digest preimages retain their meaning.
New readers replay mixed journals, while older readers reject new tags. Rollback
must use readers supporting the complete journal and may not discard new records
or reinterpret old assertions. Independently admitted predecessor tabular
payloads remain structurally loadable under current lineage and revocation checks.
New candidates must be refitted and independently repinned: half-LSB targets,
conservative geometry and expanded reference/learner/world digest preimages can
change identities. World-model V2 retained digests do not accept manually assembled
legacy in-memory model objects; refit those source-only candidates before use.
Signed-owner V2 is additive. Structural V1 regularity remains compatibility-only;
signed V2 qualification now refuses incomplete budgets. Correcting terminal
diagnostic rounding and the staged six-cell golden can change one-LSB values and
candidate identities. The exact OOD comparison restores a valid boundary value.

## Executed validation

### Third review: canonical contract and real cognitive consumer

- Protocol mutation regressions: **3 passed**. Existing validators reject a
  missing artifact schema, disabled unknown-critical-field policy and an
  unbounded `errorBudget`. The validator was not weakened.
- Module-registry, algorithm-workflow, algorithm-semantics and Lane E registry
  suites: **23 passed**. Development documentation checks passed for **40
  modules, 21 algorithm protocols and 59 critical protocols**.
- Independent finite mathematical check:
  [`qualification/check_arithmetic.py`](qualification/check_arithmetic.py),
  SHA-256 `d048076eaa53c2a530587205e1487d16fe34b464b8a82a522ec204ee3da5cdb6`.
  It checked 180 attained-statistics cases derived from 7,380 small sample
  tuples, 4,680 Hamilton vectors/18,056 branch probabilities, and 1,997 seeded
  sensor-separation comparisons. Of these sensor cases, 1,925 had positive
  quantized separation and also checked mesh rounding; 72 zero-separation
  cases made no mesh assertion and three attempts had fewer than two unique
  points. No discrepancy was found. These are independent finite arithmetic
  checks, not Rust execution or an infinite-domain proof.
- A source-exact archived SQLite/ranker case **passed**, proving that the old
  implementation accepted the reordered/self-rehashed response with its
  genuine receipt. Two separately archived signed-CURRENT barrier cases also
  **passed**, proving old read and final-use paths accepted a source forgotten
  while awaiting a provider. The first build failed from shared disk exhaustion;
  the cached serial retries completed. An initial repaired native-source run
  completed **28 passed, 0 skipped** before the subsequent CURRENT-window
  tightening. The final real-source minimal manifest completed **29 passed,
  0 skipped**, including all original scoped cognitive, SQLite/ranker, HNMF
  and ledger cases plus the new issuance/budget/barrier/publication regressions.
  The new CURRENT case uses an actual fitted/encoded/pinned model, a newly signed
  revoked registry and the real ledger sink; refusal leaves zero rows and no
  usable issuance. Clock regression, full capacity and expiry also leave zero
  exposure rows. Ranker production source SHA-256:
  `8ce723c887bdac98869b4a1e169e2363c2c7ef4ecffe979a340dd052e552f45e`;
  five-case native test-prefix SHA-256:
  `92251b2ca5c68a5409141365f4b9b222f989db3ca9b29cd93c564d6d2c8fe4a6`.
  Protocol structs are an exact native source copy; other covered host modules
  are directly referenced. This does not compile the full AgentdState/control
  IPC lifecycle or replace complete Agentd/Core/App Server integration.
- Consumer minimal-manifest `just fix`: **passed**, with six warnings from
  existing API arity and host interfaces omitted by the scoped manifest.
  Actual private issuer source/tests strict Clippy (`-D warnings`): **passed**.
  `just fix -p codex-hepta-bellman-operator`, final `just fmt` and
  `git diff --check`: **passed**. No tests were rerun after fix/format.
  Source hashes above identify bytes actually executed before final formatting.
- Full `just fix -p codex-hepta-agentd` was attempted with both the repository
  default debug profile and a serialized zero-debug retry. Both failed from
  shared disk exhaustion in dependencies, before completing the package.
  This is a resource-blocked package check, not a successful Agentd result.

### Fourth review: current execution and CI attribution

- Direct original-source library manifests executed **184 passed**: all **51
  operator** and **133 Ledger** library regressions. One existing opt-in
  target-host signed growth measurement was skipped. The minimal manifests use
  the real library entrypoints and transitive crates; they omit package examples
  and do not establish a full-workspace result. The new protocol's **15 cases**
  cover core/codec/checkpoint, durable recovery, segmented rotation and witnessed
  product admission. An initial test compilation exposed three ambiguous macro
  imports; explicit `pretty_assertions::assert_eq` imports fixed them before the
  successful run. No source behavior failure was suppressed.
- The native-source consumer manifest executed **38 passed, 0 skipped**,
  including seven new transport/worker-budget regressions and real SQLite
  ranking. Ranker and learning-sink production files were copied byte-for-byte;
  context, issuer and delivery modules were direct native source paths. The
  ranker test prefix was bytes `0..17510`, SHA-256
  `6deda5e77dac297bb1ca155dfe8f8ae67f89162f6a2576555156465f48e27ac7`.
  Only bytes `86..170` of the sink test registration were omitted: the full
  AgentdState/control socket registration, not a rewritten test implementation.
  The new seven-case helper source SHA-256 was
  `49e8a804c7e2d8b03d2692d65cc53bb13220b13f05815169516b95520a58d44f`.
  These hashes identify the executed pre-format source. Complete ranges and
  hashes are retained in the local `PROVENANCE.json`. The initial build lacked
  `pkg-config`; specifying the already installed OpenSSL headers and library
  directories allowed the real dependencies to compile. This manifest does not
  compile the complete Agentd package or execute its real socket case.
- A final independent review found legal/selected bridge lengths were checked
  only after native observation validation. Both bounds now reject before its
  scans/sets. The additional named native Ledger regression **1 passed** in a
  new validation cycle; its other 134 cases were outside that filter. The
  protocol now has **16 cases**. Existing suites were not repeated for this
  change; final package fix/format follows this last behavior check.
- Bellman/schema plus existing algorithm/workflow/module/Lane-E Python suites:
  **32 passed**. Workflow/execution-record tests: **44 passed**. The first root
  Python invocation used an incorrect workflow test-module name; the corrected
  six-case module passed. Development documentation and algorithm verifiers
  passed before final documentation refresh. These are metadata/behavior checks,
  not wire-conformance, production or scientific acceptance receipts.
- Remote architecture source-head job [110409107021](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36873960166/job/110409107021)
  executed commit `b693ef879854701c0c12cadaeae4db5c7c56a89c` and did compile the
  actual Agentd package: the named generation/reload/rollback regression **1
  passed**. Ledger **118 passed**, evaluation closure **17 passed**, self-evolution
  selection **3 passed** and independent selector admission **1 passed** also
  executed. This supersedes the earlier absence of full Agentd compilation
  evidence for that old head; it does not execute this review's new publication
  code. The workflow failed later because the independent `runtime_executable`
  filter observed zero passing tests despite command exit zero. That gate was
  preserved. Same-tree synthetic-merge reuse is not a second executed native run.
- The automatic learning qualification step now adds separate transport-fault,
  named real-socket and Ledger publication receipts with minimum **7 / 1 / 16**
  passing cases, while preserving existing commands and gates. Configuration and
  test source alone do not establish execution; the new delivered head must
  complete these remote package and socket checks.
- Native `just fix -p codex-hepta-bellman-operator -p
  codex-hepta-learning-ledger` and the real-source consumer manifest fix passed.
  The complete original `codex-hepta-agentd` package's `just fix --tests` also
  passed, including compilation of the new real socket case. The final three-
  package fix after the additional bound regression passed. Existing package
  warnings remain; this is not a strict warning-free result or socket execution.
  The two new socket test guard warnings were addressed with lexical scopes,
  without changing assertions. Clippy's equivalent `inspect_err` rewrite was
  retained. Final Agentd fix, `just fmt` and `git diff --check` passed; the two
  new guard warnings are gone. No functional tests were repeated after final
  fix/format. The final independent scoped review found no further concrete
  defect; the external integration and acceptance limits above remain open.

### Previously executed operator and owner qualification

- `just test --locked --offline -p codex-hepta-bellman-operator`: **47 passed, 0 skipped**.
- The pre-fix scheduled-revocation/expiry reproduction passed by proving that
  old fit accepted both inputs while the current verifier rejected them. The
  repaired regression now requires both fit failures and also verifies a valid
  fit plus unchanged predictions after a later owner head.
- Real synchronous terminal-owner integration: **5 passed, 0 skipped**. The
  existing Agentd test prefix and real support file ran unchanged in a minimal
  manifest using the actual LedgerWriter, artifact owner and operator crates.
  The prefix SHA-256 was
  `569f83119b57588b88b8eabdb6408a2ed0616a29a621adeea4c449efaa3d972a`;
  support SHA-256 was
  `be2a3e4e2a5d6be30971b2334383692788ffc0d8f4adc9196786b945c9f4332d`.
  This covers correction/withdrawal, foreign receipt context/frontiers,
  authenticated trust rotation, scheduled revocation, evidence expiry and exact
  signed complete-dataset freeze. The hash identifies bytes executed before
  subsequent formatting; no test logic was rewritten.
- Actual cognitive-ranker source and four unchanged original unit cases:
  **4 passed, 0 skipped** in a minimal manifest. Native source SHA-256:
  `8ce723c887bdac98869b4a1e169e2363c2c7ef4ecffe979a340dd052e552f45e`;
  test-prefix SHA-256:
  `a1413aa7dfa93d7801be8f4d702e5578859c75ff526eabccf5c13b0a49c9912b`.
  The protocol item schema is an exact source copy. SQLite/socket cases are
  excluded; these are real ranker unit checks, not a complete Agentd result.
- Unchanged original shadow durable-roundtrip target and support files, directly
  referenced by a minimal manifest: **3 passed, 1 ignored parent-only worker**.
  Both substantive cross-process parent regressions passed; the ignored worker
  is executed by its parent with its explicit worker-only input. This covers
  actual artifact-owner persistence, separately admitted tabular predictions in
  new processes, current revocation and refused revoked rollback.
- Complete original terminal-owner/shared-Replay test target, directly compiled
  with the actual adapter source, Memory/SQLite, LedgerWriter and artifact crates:
  **6 passed, 1 ignored local performance profile**. This includes the same five
  owner regressions above plus the full asynchronous source grant, wrong signed
  plan, expired signed evidence, V1/V2 artifact equality, persistence/load/predict
  and source-withdrawal chain. The performance profile is opt-in, not a missed
  functional test. The minimal manifest omits unrelated Agentd/App Server code;
  the adapter, full test file and original support file are not rewritten.
  Both its complete test-target compilation and strict Clippy (`-D warnings`)
  **passed**.
- Operator all-target compilation and final strict all-target Clippy
  (`-D warnings`): **passed**. `just fix -p codex-hepta-bellman-operator`,
  `just fmt` and `git diff --check`: **passed**.
- Development module-document verification: **40 modules passed**. Algorithm
  documentation/paper locks and Lane E registry unit tests (**6 passed**):
  **passed**. Exact-source map checks for the six reviewed operator/direct-owner
  mappings are recorded against the delivered commit in the PR. The original
  main contained 19 non-ancestral map anchors; rebinding this scope leaves 14
  unrelated modules with that pre-existing global qualification limitation.
  Original source provenance is retained separately; no historical execution,
  deployment or acceptance claim is renewed by navigation rebinding.
- Full Agentd package and control-socket/lifecycle integration:
  **not completed**. Compilation exceeded the shared disk and memory limits;
  the serialized retry was also interrupted by premature cleanup of its build
  directory. No full Agentd package result is claimed. The minimal real-owner
  and scoped real-ranker/shared-Replay/shadow runs do not substitute for those
  remaining integration checks. Real SQLite/ranker integration now passed in
  the third review's native-source minimal manifest above, and shared Replay
  completed its real-source integration run after resources became available.
- Global Lane E closure: **failed with 8 pre-existing findings** in legacy V1
  Decision/Outcome product-writer paths in objective ingress and intelligence
  product/runner. A clean baseline worktree produced the identical finding list.
  The validator and bypass gates are unchanged; this audit does not count a
  failing global check as a pass.
- PR CI has not been claimed green. The observed earlier candidate's general
  repository checks fail on an unchanged privileged-boundary classification
  and malformed regex test; a Windows Bazel launch also failed before any
  reported Rust action. The source-head architecture job for `35a7e23d` also
  failed its required-observed-tests gate: the `runtime_executable` filtered
  native command exited zero but observed zero passing tests. The minimum-test
  gate remains intact; this is not a successful lifecycle qualification.
  Workflow status is read live and remains separate from scoped validation.

Test references name executable cases; they are not deployment or acceptance
receipts. The final PR records actual check results and the remaining global gate.
