# Real utility evaluation: source repair and qualification evidence

**HOLD — source and software evidence do not establish a completed ordinary learning deployment.**

This evidence branch records work for [PR #6203](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6203). The production-source head is `19aa601fa09321f1b6d1b3ff3b4d422908004e48`, tree `8f7d13bd9e0b737354ea37e62edd88fcc26b8500`. Evidence-only commits are separate from that source PR.

Checkpoint observed at **2026-11-12 08:05:56 UTC**. This checkpoint preserves the completed audit and observed results. The original raw-record package was prepared and verified in the local execution environment; the original task directory is unavailable in the replacement executor view. The raw files are not claimed to be included in this initial checkpoint. Pending local executions remain **Unknown** until their original terminal records can be read. At 08:07 UTC the replacement executor accepted commands, but `/workspace/scratch/36fa460df1de` was absent. This does not supply an exit status for either original job.

## What changed

A failed metric previously took precedence over a missing applicable evidence gate in both the independent comparator and its trusted in-process compatibility path. That could classify an incomplete comparison as `Ineligible`, which the learning bridge interprets as a completed negative `NoUpdate`.

The repair gives `InsufficientEvidence` precedence, retains the known failed metrics, and preserves complete positive and complete negative decisions. The learning-stage regression combines a known negative comparison with a missing future window and requires the original Training cut to remain unchanged at Evaluation. It also retains current signature checks.

Two inherited QA lists were aligned to the actual registered original Model callers without changing exact equality or rejection of unregistered callers. A later complete-caller failure exposed two ambiguous `self.journal.readback` expressions in a split Model implementation. Both now explicitly call the same `ProductEvaluationExecutionStoreV1` trait with the same original journal, key, mutable borrow and result. The verifier and caller manifest were not weakened.

The source PR contains three commits, **10 files, +232/-12** against the frozen #6163 base.

## Source identities

| Role | Commit | Tree |
| --- | --- | --- |
| Frozen published #6163 base | `eabfb55ef388c750725884713c2f1fe9044b334f` | `e68a7ffb394bdac721259fd6295d799800d564c3` |
| Utility precedence repair; actually executed eval library | `91d0e10e002d285aec720e9f2b2f3a1d854b4707` | `8cd35e01cc02146606457a8481ecc1d8dda22158` |
| Two QA expectation corrections | `6d0da9fe0cae414975288f23a3779d7bf86e3638` | `fefb5d02dbd981b508727f7ffaf93fc68b720976` |
| Explicit journal calls; current source | `19aa601fa09321f1b6d1b3ff3b4d422908004e48` | `8f7d13bd9e0b737354ea37e62edd88fcc26b8500` |
| Isolated old-production control, local only | `814bf1eb96cd3165667585be2880000b76bea42a` | `93024822ce8d903b6d03ab37982738fe92b5dcb8` |

The first four source cuts have actual GitHub objects. Changed source blobs were read back in full, and the expected parent, complete tree and branch ref were checked. Git object identity is not a signature by an independent evaluator or an adoption authorization.

The audit originally inspected local `0b450608d0fa577b2d4c4c198883e7f5a432bf92` and `b19f15923760da49cf735f550da3a50beb9c50a2`. Their complete trees match the published base and utility repair respectively. The unchanged original audit is preserved in [SOURCE_AUDIT.md](SOURCE_AUDIT.md); its original review identity is not silently changed to a later execution.

## Observed checks and their exact scope

| Check | Observed result | Attribution and limit |
| --- | --- | --- |
| Original scoped eval maintenance | `just fix -p codex-hepta-intelligence-eval --locked --offline` and the repository formatter passed | Clean `91d0e10e` before and after |
| Complete default-feature eval library | **163 passed, 0 failed, 0 skipped** | Actual `just test -p codex-hepta-intelligence-eval --lib --locked --offline --retries 0` on `91d0e10e`; fresh JUnit verified |
| Isolated prior-production control | **0 passed, 4 failed; 159 filtered out** | Actual exit 100 on local `814bf1eb`; all four new methods show actual `Ineligible` versus expected `InsufficientEvidence`. Only the two old production branch orders were restored; new assertions were unchanged |
| Initial complete source closure | **344 passed, 2 failed**, exit 1 | Actual `91d0e10e`; both stale QA failures retained |
| QA-corrected complete source closure | **346 passed, 0 failed**, exit 0 | Actual clean `6d0da9fe`; full source inventory unchanged |
| Initial full caller verifier | **Failed**, exit 1 after 876.408 seconds; not a timeout | Actual clean `91d0e10e`; unresolved Model journal receiver. Identical verifier inputs on 6d do not convert the failure into a pass |
| Explicit-call diagnostic | Original failing boundary resolved successfully over the complete 6,589-file Rust source index | Local `20af3812735118b69b8bfac92a44b32f1326f6eb`, same entire tree as `19aa601f`; this is one boundary, not a full-verifier pass |
| Additional diagnostic scan | Incomplete, SIGKILL / return code -9; cause Unknown | Original record says no timeout. No complete broad-scan pass is claimed |
| Final complete source closure and full caller verifier | **Unknown at environment disconnection** | Exact clean `19aa601f`; both started around 08:01 UTC. Source-closure budget 600 seconds and full-verifier budget 4800 seconds were retained. The new caller self-test had passed |
| agentd behavior, ordinary suite and Root suite | **Pending** | Desktop locked dependency fetch passed with source and Cargo.lock unchanged; original agentd maintenance was compiling on clean 6d. The next persistent operation is bound to exact 19aa after the original maintenance terminates |

The successful eval execution is not relabeled as an execution on a successor. A separate comparison read all 205 eval/dependency/build inputs at 91d and 6d byte-for-byte and verified equality. The 6d-to-19aa comparison changes only the one agentd file, outside that set. A newly generated [remote source-equivalence record](REMOTE_EVAL_INPUT_EQUIVALENCE_91D0_19AA.json) resolves all 205 selected paths from 91d and 19aa, checks identical mode/type/blob/size, and verifies the complete changed-path set has no intersection. Its 13 Git-tree responses are untruncated. This is Git object identity evidence; it does not restore the lost SHA256 list or claim any new execution.

### Raw-package state at disconnection

The following hashes identify the original locally prepared packages; those packages are not represented as restored:

- Eval package manifest: `3a8f290076513a035afd8b33d0f926fa5ba89cc9738afa84d8d3c4320a0997d5`, 25 stored files and 262,178 bytes. Seventeen raw originals were copied without altering their bytes.
- Source-gates package manifest: `d06c893de93a26d6aaa27d4aa265429715c3c7f863981dc9e23af287b05d2ad7`, 40 original logical files represented by 79 stored files. Large original inventories were split into at most 262,144-byte parts with per-part and whole-file hashes and verified reconstruction.
- Final 19aa pre-execution inventory: 14,739 entries, `a4f9a1ef68e1eb5c879030dfa82c42cccc9ab71744cecddf59c37f33cd204848`.
- The two old worktree cleanup operations had **not** been started when the environment disconnected. No cleanup completion is inferred.

## Four distinct outcomes

| Outcome | Required meaning | Boundary preserved by this work |
| --- | --- | --- |
| Adopt | Complete evidence passes utility and every hard gate; original owners authorize the actual new version and actual use | Evaluator eligibility retains deny-all authority. It does not publish, adopt, pay or create FinalUse rights |
| Complete NoUpdate / Ineligible | Evidence is complete and supports retaining the parent | Known negatives remain recorded; a changed Training Candidate cannot be relabeled an unchanged TrainingNoUpdate |
| InsufficientEvidence / Unknown | A required result, cost, provenance, support, independence or authority is missing | No completed-negative Evaluation receipt is fabricated; original evidence and known failures remain available |
| Objective Fraud | A separately reproducible deterministic violation under its challenge and disposition contract | Missing evidence, an estimator error or a bad score does not itself establish fraud |

Current revalidation recomputes the full sealed decision. An old incomplete result that was labeled Ineligible cannot silently inherit a completed NoUpdate qualification under the repaired logic. Original receipts are preserved rather than rewritten.

## Why the full ordinary goal remains open

The target remains actual authorized A, original Training, independent B, owner-authorized Adopt or complete NoUpdate, a distinct ordinary consumer C, and daemon plus Root cold recovery.

The inspected code contains real original Model Proposal, evaluated-retention context, publication and read-only recovery components. It also deliberately refuses paths without the actual owners. The strict unchanged-training route has three receipts before Selection; evaluated NoUpdate has a changed Candidate and a fourth, independent Evaluation receipt. Existing ordinary live-read, Selector and C purposes cannot consume that new profile. Root and Candidate routing need the corresponding explicit full-signature profile; removing their current refusal would not supply the missing authority.

Additional open requirements are the complete deployable identity and strongest deployable baseline, all registered old/rare/safety and privacy/authorization constraints, full lifecycle cost accounting, authenticated task/model/evaluator/control provenance, supported action-dependent outcomes, and available authorized material actually read and used by C. A digest identifies bytes; it does not by itself establish any of those external facts.

**Complete real ordinary Adopt: 0. Complete real ordinary evaluated NoUpdate: 0. Complete daemon-plus-Root cold recovery qualification: 0.**

The repository test fixtures establish software mechanisms within their stated scopes. They create no independent real task distribution, observed causal improvement, model availability guarantee, public reward contract or permission to activate production.

## Additional preserved material

- [Original caller failure output](recovered-tool-output/91d0-caller-verify.log) and [caller self-test output](recovered-tool-output/91d0-caller-self-test.log) were recovered from complete previously observed tool outputs and match their original byte counts and SHA256. The [new recovery note](recovered-tool-output/recovery-note.json) distinguishes these two exact payloads from unavailable original inventories and closure logs. Its proposed paths retain the original package prefix; actual repository paths add `qa/`.
- [Original 6d maintenance patch](native/agentd-6d-maintenance.patch) preserves all ten automatic postimages' diff, before any review or formatting. It is a failed maintenance result, not a source-head test pass.
- [Ordinary integration map](ORDINARY_INTEGRATION_MAP.md) identifies the real reusable owners and the complete proposed Version/live-read/Selector/C/Root changes. It explicitly describes unimplemented work. Adding a Version purpose alone cannot close the ordinary chain.

Raw log/JUnit files from the original local 163-test run and the four-test old-code control remain unavailable. Their observed outcomes are kept as historical observations; no reconstructed summary is presented as their original byte record.
