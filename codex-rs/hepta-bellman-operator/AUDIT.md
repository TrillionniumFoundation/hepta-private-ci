# learning.operator adversarial audit — 2026-10-01

## Scope and source

Base: `997e7beef8151160065df36b024bc8da5c989e93` on repository `main`.
The reviewed source is `codex-rs/hepta-bellman-operator`, with explicit
cross-owner integration scope limited to Agentd cognitive ranking, the shared
Replay terminal adapter and their regression fixtures. No durable writer or selection authority is
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
| Development documentation | Detailed guides, current algorithms/limits/trust tiers and operation/caller mappings; design targets remain explicit |
| Native offline baseline | Target arithmetic, sensor design, complete tabular fitting, action-conditioned world model, signed qualification, pinned persistence and owner-derived terminal profile are implemented |
| Explicit integration | Cognitive read consumer and shared replay terminal consumer with signed-owner training exist; neither is a default autonomous learning loop |
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

## Compatibility and rollback

No persisted payload layout changes. Independently admitted predecessor tabular
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
- Full Agentd package and cognitive SQLite/socket integration:
  **not completed**. Compilation exceeded the shared disk and memory limits;
  the serialized retry was also interrupted by premature cleanup of its build
  directory. No full Agentd package result is claimed. The minimal real-owner
  and scoped real-ranker/shared-Replay/shadow runs do not substitute for those
  remaining integration checks. The new shared-Replay path did complete its
  real-source integration run after resources became available.
- Global Lane E closure: **failed with 8 pre-existing findings** in legacy V1
  Decision/Outcome product-writer paths in objective ingress and intelligence
  product/runner. A clean baseline worktree produced the identical finding list.
  The validator and bypass gates are unchanged; this audit does not count a
  failing global check as a pass.
- PR CI has not been claimed green. The observed earlier candidate's general
  repository checks fail on an unchanged privileged-boundary classification
  and malformed regex test; a Windows Bazel launch also failed before any
  reported Rust action. Workflow status is read live and remains separate from
  scoped local validation.

Test references name executable cases; they are not deployment or acceptance
receipts. The final PR records actual check results and the remaining global gate.
