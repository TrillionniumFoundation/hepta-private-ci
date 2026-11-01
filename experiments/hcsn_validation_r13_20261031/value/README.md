# R13: eliminate public, deterministic SKIP-to-STOP tails

This additive repair preserves the six fixed R12 content models and all four
controllers per core. Every original controller is retained alongside its
transformed counterpart, including the stronger matched-Qstar control.
There is no refitting, threshold selection or content training in this study.

## Exact claim and proof

Under the inherited finite contract, SKIP leaves content state h unchanged,
changes only the public slot and pending time, and charges a nonnegative fee.
STOP predicts from h alone. The controller is frozen and deterministic.

Consider any latent raw world. The wrapper follows the original policy until
it can determine, solely from public simulated SKIP successors, that the
original would stop without any intervening READ. It then stops immediately.
If a READ is encountered while checking, the wrapper stops checking and returns
the original SKIP; it never executes or samples that hypothetical READ.
Thus actual READ slots, accepted raw observations, READ successors and terminal
prediction are unchanged on every world. If the deleted tail has k SKIPs,
the task-return difference is exactly k times the nonnegative SKIP tariff.
This also holds from every intermediate causal prefix. Applying the same
transformation again has no effect; nested wrappers are flattened explicitly.

This proof does not apply if a waiting action changes h, a deadline changes
terminal utility, or policies have mutable decision state. It proves task-tariff
dominance, not lower CPU or universally superior decisions. Extra public policy
calls are real computation and are included in actor and outer process timing.
No missing RECOVER/CONTINUE action is created by renaming SKIP.

## Scores, evidence and configuration scope

The returned critic scores remain the original trained scores. The executed
policy changes; its Qpi is recomputed over every reachable history. This keeps
calibration errors visible instead of inventing a new perfect critic. Regret,
all four factorials, both matched-Qstar controls, initial STOP failures, exact
task fees and actor CPU/wall are retained.

The four confirm13 configurations are fixed in PROTOCOL.json before evaluation.
Only three existing fitted seeds exist; configurations are conditions, not new
independent fits. Already-seen R12 records are analyzed separately and labeled
retrospective. The independent lazy executor forces every legal first action
at root and one selected occupied intermediate prefix for all eight policies.
An intermediate prefix containing an actual READ is preferred when available.
All-history numerical values and bounded actual-prefix coverage are distinct.

## Reproduction

Run with NumPy/SciPy and one BLAS thread. The full-process supervisor uses Linux
wait4; it retains child CPU, wall and maximum RSS including startup and exit.

    python -B -m experiments.hcsn_validation_r13_20261031.value.tests -v
    python -B -m experiments.hcsn_validation_r13_20261031.value.run freeze

Freeze binds all local source bytes and every inherited input checked by the
loader. Before confirmation, publish those files and SOURCE_FREEZE.json, then
write SOURCE_PUBLICATION_READBACK.json with verified=true, remote commit_sha,
source_freeze_sha256 and files_sha256. The latter must map every frozen source
and SOURCE_FREEZE.json repository-relative path to its remotely read-back hash.
Evaluation refuses changed sources, inherited selected payloads or a missing
publication receipt. Do not recreate a freeze to conceal post-result edits.

    python -B -m experiments.hcsn_validation_r13_20261031.value.run supervise \
      --out experiments/hcsn_validation_r13_20261031/value/evidence/confirmation_01

Outputs require a new directory; failed attempts retain FAILURE.json. The outer
confirmation_01_PROCESS.json is written only after the child exits. Actor/stage
times are nested inside it and must not be added again. The prior R12 training
receipt is carried as inherited work; R13 adds zero training, not zero inherited
training cost. No device energy or GPU measurement is available.
