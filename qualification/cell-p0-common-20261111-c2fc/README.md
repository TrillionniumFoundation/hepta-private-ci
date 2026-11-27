# Common Cell candidate: source convergence and adoption boundaries

## Candidate inputs

This increment is based on the published common candidate in PR #5875,
`b5019ee98bc7b7b99eb689378f41e66691c2d257` (tree
`5164d68c23ffa071a80d4aa9a7f033f068a82dfd`). The review baseline is pinned to this commit. Its ancestry already contains the
ordinary Q24 branch `f97f3c90ac1ac3d5171fd9f25b3e34431f44a367`, original recovery
branch `0c99a30dbe9307d48aa50ffc63404235ade8ae9c`, and maintained native source
`c7633658aef42077f51fa71a1b727b4653ddb76b`.

Before published-head validation, the candidate also incorporates the published
compile repair `a15acbf4db6178523a9297033c86e3be0b2725a3`: the new
`TrainingNoUpdateV2` observation is exhaustively rejected as a completed
generation use. It cannot become NextUse or FinalUse merely because training
returned no candidate. The existing rejection semantics and owner boundaries
remain in force.

The later published base includes the original Q24 training receipt owner. It
materializes signed Training and TrainingNoUpdate observations from the original
training owner. Its create/recover/attest/readback product entry boundaries and
the original stage-assembly boundary remain closed. The original training
observation reader admits only this receipt-owner module as an internal caller;
that edge does not constitute ordinary product or Root enrollment.

The recovery-test collision preserves the base's original `initial.snapshot()`
and the explicit duplicate-claim `false` assertion against the original digest.
The first claim remains `true`, and the original complete claimed vector is
compared before and after recovery without rebuilding or shadowing its state.
The earlier S E0425 compile failure and T's separate checks remain historical
results; they do not qualify the final merged source.

Two published changes are merged with their histories:

- PR #5867, `fbec51e7177892782d3874fc5547771d9728a17d`: incomplete cost coverage
  leaves arm and campaign totals unknown. Recorded partial amounts remain
  separately identified subtotals. Planned, unobserved opportunities remain in
  the denominator.
- PR #5877, `5af2dd4582a6bf0aa9a3b2a42bb8e5854a029170`: remove the shorter
  test-only policy deadline, exercise a legal 600 ms response under the existing
  production five-second limit, retain timeout diagnostics, and verify the
  resolved policy's current authentication generation and exactly three requests.
  The merge retains the base's more specific auth-refresh diagnostic.

The base already has the RMCP 3.9 typed metadata/cause and redirect diagnostic
compatibility fixes. It also retains the reliable unified-exec transcript path
and the additional local/remote transcript tests. Their original security,
resource, truncation, timeout and rejection assertions remain in the candidate.
The two read-only reconciliation reports here identify their exact blobs and
limitations. In particular, the transcript evidence does not establish lossless
output upstream of the reliable receiver boundary.

## Preserved failed assembly

An earlier independently assembled code tree,
`9821f01f3e0c25da98acc1016c3e78ed269f0786`, passed its 76 research-gate tests but
failed the source-closure run: unittest reported 133 tests, one failure and
14 errors, including subtest errors. A generic function marker was invalid for
the verifier, and a registry scope check hidden inside a dead block escaped a
manifest rule. Its positive full scan was cancelled after these concrete
failures; no passing scan is inferred.

The original failure log and analysis are retained. The candidate uses the
published successor's corrected manifest and associated mutations, which were
independently compared with the original runtime/authentication code. The
invalid generic marker is not reintroduced. Results from that earlier tree are
not qualification of this candidate's source commit.

## Validation contract

The candidate source commit, its complete tree, tool versions, commands, raw
logs, failed attempts, and maintenance postimage must remain distinguishable.
Native results must identify the actual executed source; a later commit or
another commit with the same tree does not automatically inherit qualification.

`run_native_candidate.py` is a reusable driver prepared from the maintained
native workflow. Its accompanying reference and static-review files describe
what was checked during preparation. Static review is not a native execution.
The driver requires clean exact HEAD, new output/target directories, a helper
built from that same source, three complete library packages, fresh JUnit and
seven exact Root test names. Missing Root prerequisites produce `NOT_RUN` and
an incomplete final result. It does not create production owner credentials.

Local validation results and exact-head hosted results are recorded separately
in the review evidence referenced by the pull request. Source guards, fixture
tests, native tests and hosted whole-workflow status are separate observations.
No historical pass count is added to the new candidate's pass count. Formatting
or lint changes after a test are retained as postimages; behavior tests are not
repeated solely after maintenance.

## P0 adoption remains HOLD

This work establishes a reviewable shared source candidate. It does not supply
the missing production Model Proposal profile or enroll original stage owners.
The ordinary production A -> learning -> independent B evaluation -> C use ->
daemon/Root cold-recovery chain has no completed confirmation in this evidence.
Positive adoption and complete correct NoUpdate/rollback acceptance likewise
remain unestablished.

The frozen Q24 trainer produces a Model artifact. Parameter V3 and Topology
proposal protocols cannot be relabelled to admit that artifact. A versioned
Model protocol needs its original durable owner, anchor acknowledgement,
readback/recovery, current-source/withdrawal checks and original Root enrollment.
Existing test-only research proposals and uncommitted material-owner drafts do
not grant that authority. The four receipt materialization product boundaries
and original stage-assembly entry remain closed. The training-observation
reader's single receipt-owner caller is an internal edge, not ordinary product
enrollment.

Actual original model, data, configuration, Circuit and evaluator identities,
precommitted independent evaluation, matched training/baseline histories and
complete costs must be established before production or scientific adoption.
Missing originals remain missing, and unknown costs remain unknown.

## P1 evidence and later stages

`P1_ADOPTION_MATRIX.json` contains fixed-source evidence and source links for
PERC, ACT, VERIFY and PRED. The compact version gives the decision table.

- PERC now has a real encoder comparison on 30 distinct synthetic tasks across
  three seeds: Rules 90/90, Global 49/90, Dense 63/90. This supersedes the old
  known-DEV-only description but adds no independent real-source confirmation.
- ACT's 3,200 episodes per execution remain 80 designated instances across
  repeated seeds and five labelled arms, with substantial shared task and policy
  structure. Replaying the exposed set does not create new independent units.
- VERIFY's test, SQLite row, scenario and subprocess counts remain separate.
  Platform smoke success does not establish independent real-task policy benefit.
- PRED's 189 fits are development execution, not 189 confirmations. Later
  synthetic train/dev fixtures do not enlarge the real confirmation denominator.

MEM selector evidence remains distinct from retention/memory benefit: 54 pairs
from 14 source groups cannot be treated as 54 independent source groups. The
separate MEM7 capacity record in PR #5872 is one synthetic public-API run at
4,096 records and two cold reader processes, with zero new real confirmations.
CTRL's retained uncertain dispatch remains `UNKNOWN`; an exact-key recovery
timeout is not evidence that the underlying work did not execute.

Keep topology fixed while testing task benefit above strong baselines. P2
credit, clocks, replay and kernel comparisons require that benefit first. P3
topology changes additionally need state migration, cost, recovery and retention
evidence. P4 learner/RSI comparisons require frozen/current/generated learners,
same-experience no-update controls, new task families, multiple windows and full
learner-generation cost. None of these later-stage claims is admitted here.
