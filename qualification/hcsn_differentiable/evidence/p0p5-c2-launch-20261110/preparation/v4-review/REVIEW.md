# Independent C2 v4 reporting and budget review

## Conclusion and permitted inference

No source blocker was identified in the frozen v3-to-v4 reporting delta for a
separately authorized six-chain diagnostic continuation. The delta changes
reporting fields and aggregation, not training, restoration, ordering, posterior
capture, stopping, or the declared resource envelope. This review does not
authorize execution. Numerical qualification and scientific benefit remain
HOLD; training-adequacy credit still requires the complete terminal gate.

This was a static review plus a stdlib-only source/AST/receipt check. It did not
load a production checkpoint, import the producer, rerun software tests, or run
a forward pass, optimizer, finite-difference calculation, or numerical oracle.
`RESULT.json` binds every inspected source and original receipt by bytes and
SHA256. `RECEIPT.json` records the complete independent verification child:
0.141124270 seconds wall and 0.137377 seconds waited CPU. Human/source-reading
time outside this child is not represented as measured child CPU.

## Exact source delta and validation lineage

- v3 program manifest: `ed02f75a65fd1a5958e289d9b6a812a2feddb0096b787fbcc5b37331d0965648`.
- v4 program manifest: `322eb8f76cce589ba44ed66eff822f7b497e6507106a1ad56a65bdc8c83f7f57`.
- v4 tested source ZIP: 209,455 bytes, SHA256
  `95d53c9a8fd7b6d0d60388b29d58519160c1d04357069bd805e5f4bfa2c91079`.

The complete v4 capsule and all declared v3/v4 file identities match their
manifests. The only changed pre-existing files are `c2_runner.py`,
`c2_controller.py`, and `test_c2_execution.py`. The runner's AST is identical
after removing only the old/new reporting dictionary fields. Controller
execution functions are identical under the same normalization; the remaining
changes are confined to `cost_totals` and `terminal_result_gate`.

The ambiguous `formal_fits_started: 0` is replaced with
`fresh_independent_fits_started: 0`. That zero means no new independent seed/LR
roster. It does not mean no continuation work. The runner reports one
continuation attempt and retains its counter of optimizer calls that returned
successfully. The controller still counts actual child launches, carries valid
terminal completed-update counters, and marks aggregate updates as a lower
bound when launches or terminal records are unknown. A missing terminal report
cannot become a known zero-update success. Failed phases with valid reports
retain their reported completed updates and separately measured exit costs.

The original native v3 receipt is byte-bound to the v3 sources: its four
software-suite children represent 53 synthetic tests, and its six production
parent children only validate the existing chains. All ten returned zero.
No production forward, backward, or optimizer update is credited to that
preflight. V4 instead has the retained cloud validation of one existing tiny
synthetic restoration test plus four reporting tests, all passed. Its original
complete child cost was 4.538071392 seconds wall and 4.088808 seconds CPU.
**V4 was not fully retested on the native host.** The exact delta supports
reusing the unchanged v3 evidence within its original scope; it does not rename
those historical tests as v4 native execution.

## 120-second capture policy and 600-second reserve

`ProgressRecorder.capture` starts one clock per capture slot, before loading
the supplied checkpoint and preparing state-neutrality snapshots. The loop
then processes all three declared episodes against that same clock. Therefore
`per_window_soft_wall_seconds: 120` means **120 seconds for the whole
three-episode slot**, not 120 seconds for each episode.

The checks are cooperative: before each episode and after the three-episode
loop. They do not interrupt a forward pass at exactly 120 seconds. The later
state/source-neutrality checks and receipt write are also charged, and the
final receipt can exceed that soft threshold. Terminal-last and terminal-best
are two distinct capture slots, each using this policy. Their two nominal
120-second thresholds are not hard bounds on all finalization work.

The contract's 600-second reserve is inside the unchanged cumulative
43,200-second active-process allowance. `Budget.check` stops normal training
when the remaining allowance is at most 600 seconds. During finalization its
stop threshold becomes zero, with RSS checks retained. The controller deadline
is `dispatch + 43200 - parent_full_outer_wall`; prelaunch, imports, checkpoint
I/O, recording, development evaluation, and partial original work are charged.
No reserve is added outside that limit and no old work is refunded. The
controller polls and kills at the deadline; polling/teardown overhead must be
reported at the actually observed duration, not rounded down to the cap.

Suggested public wording:

> C2 stops ordinary updates with 600 seconds remaining inside the same
> cumulative 43,200-second allowance. This internal reserve does not guarantee
> completion of terminal-last, terminal-best, full-D evaluation, integrity
> checks, and serialization. Each supplemental three-episode capture slot has
> a 120-second cooperative soft limit. Missing or failed finalization remains
> explicit and receives no training-adequacy credit.

## Failure and credit handling

A truncated, incomplete, over-budget, or state-changing capture sets
`recording_hold` and prevents another optimizer update. If the global allowance
prevents beginning a terminal slot, the slot is `not_captured_budget`; a normal
training completion becomes `budget_exhausted_finalization`. Later development
evaluation does not upgrade an existing recording failure to success. Final
source/input violations also prevent success.

Only `completed_development` with a genuine development plateau and inherited
memorization pass can set training adequacy true. Nonzero exits must retain
adequacy false. A hard timeout or missing/invalid result fails the controller's
terminal evidence gate while keeping any separately measured whole-child cost.
Successful completion of an attempt roster is not equivalent to every fit
passing this gate. None of these rules grants whole-training numerical or
independent scientific admission.
