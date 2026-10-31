# R11 native causal access and recovery audit

## Result

`evidence/native_01/SUMMARY.json` records **23 real native processes**, all
required checks passing. This uses the formatted R11 `BUILD_02.json` binary and
the frozen `training_02/models/seed81031_analytic_value.json` policy. The audit
uses copies of the earlier development fixture `train_seed81031_0000`; every
original public, packet and label byte is checked against its preserved
`training_01/data/development_seed81031.tar.gz` member. It does not access a
confirmation cohort or change a trained model for an efficacy run.

The owner selected the following actions itself:

`SKIP, SKIP, READ, FIRE, SKIP, READ, FIRE`.

Its only packet opens and completed content evaluations were
`job0_tick2.json` and `job1_tick6.json`. Linux inotify watches each copied packet
and the evaluator-label file during each subprocess. Native stdout/stderr and
these independent kernel access events are retained in each case's `raw/`
directory. The host never supplies an action, posterior, observation or packet
choice to the owner.

| Check | Executed observation |
| --- | --- |
| One complete `--steps 32` run versus successive `--steps 1 --ack …` restarts | Exact task, cell-bit and content-state equality at all 7 acknowledged boundaries. Independent uninterrupted prefix runs expose the intermediate cell states. All decision, action and task/content receipt fields also match. |
| Evaluator labels flipped from `[1, 0]` to `[0, 1]` | Exact same complete trajectory, content reads and final state. Zero kernel OPEN/ACCESS events for the label file. |
| Future packet payload changed while its declared public hash remains fixed | No access to that packet during the first 2 SKIPs. Its subsequent READ decision, Q values and pre-action features remain identical. The actual READ opens that file and rejects it with `content packet digest mismatch`; it supplies no decoded observation. A fresh `--steps 0 --ack …` process restores the failed-read state exactly. |
| Corruption of a packet the policy never reads | Corrupted `job0_tick0.json` is never opened. The complete trajectory and final task/cell/content state remain identical. |
| Stale acknowledgement, with `--steps 1` at a nonterminal checkpoint | Process rejects with `external acknowledged digest mismatch`; no packet access and no change to snapshot, journal or witness bytes. |
| Valid-shaped policy with one numeric weight changed, same live checkpoint and `--steps 1` | Process rejects with `checkpoint source/public/model/policy identity mismatch`; no packet access and no change to snapshot, journal or witness bytes. |

This audit records one frozen learned policy, not artificial constant-action
policies. The altered weight is used only for an identity-rejection request;
it is never accepted or used to produce a comparison trajectory.

## Identities

Full source and artifact bindings are in `evidence/native_01/INPUTS.json`.

| Artifact | SHA-256 |
| --- | --- |
| Training freeze | `179037fca15a4f1ff5f08a50fd7c306b6ef5fdca82c6e951caa4091e293cbb20` |
| Actual native binary | `6f5d31cc8158690c7d1f29ddd0e53832bbd6119010249886f53b309dc3552fc5` |
| Frozen analytic policy | `e5f3be95dc01095772d2e17c7e5ec3c1b9cbf198be25b042acf5e684ce37d396` |
| Native source-set digest | `3e33f6e25a6da7188e9a9b0b7800b75c6b5020cd0de96a663ee414b9a9338c29` |
| Executed audit source | `7bf19119ee75049cdc96e5601c283bc8dd00952f9ace8e1c2bd9577f26636b80` |

`AUDIT_SOURCE.py` preserves the exact audit source executed. The unmodified R10
`NativeRunner` supplies subprocess launch and raw receipts only; this audit does
not use the old unanchored-MLP policy replay or constant-policy interventions.
Build verification checks every recorded native source and cached dependency
inventory. The build's `all_dependency_archives_verified=false` qualification
remains present: some dependencies use explicitly pinned unpacked cache files.

## Resource accounting and limits

All 23 native child processes, including failed identity requests and repeated
prefixes, consumed **0.213608 CPU seconds** and **0.305180 wall seconds** in this
run. The audit parent's CPU was **0.233769 seconds**; end-to-end audit wall time
was **0.622366 seconds**. Parent CPU starts at the audit entry point and excludes
Python imports; child CPU includes process startup, artifact loading, actual
execution, persistence and exit. Nested owner/decoder timing fields must not be
added to these child totals. No energy meter was used.

The complete run used 0.011786 child CPU seconds; seven fresh one-step processes
used 0.051588 child CPU seconds. These are one development witness, with no
performance confidence interval. They do not prove a utility improvement or an
energy saving.

Recovery is tested only at acknowledged synchronous action boundaries. The
comparison excludes timing-dependent native checkpoint/receipt digests and
timings. Each run's own acknowledged snapshot hash is independently verified;
the full task, exact cell snapshot and content state are compared. This is not
a claim of exactly-once external side effects across an arbitrary mid-action
crash. Native policy/public/content-model loading can occur before an identity
rejection; the zero-access assertion concerns task packets and evaluator labels.
Inotify events can coalesce, so the access logs are not byte-count meters.

No runtime blocker was found in the declared scope. Efficacy, the separate
finite-model/continuum gap and broader crash-fault coverage remain separate
questions.

## Independent native-outcome scoring review

After `confirmation_02/COMPLETE.json` existed, `scoring.py` read its completed
archive index and original native stdout. It verified all **90 archive hashes**
and the **3,200 selected member hashes**: 2,560 native receipt files and 640
evaluator-label files. It checked every native receipt's source and frozen-model
identity, actual terminal status, and agreement of the final answer list with
its own FIRE receipts.

Scoring uses only the native `end.task.answers` and native cost fields:

\[
C=\sum_j 1\{\hat y_j^{\mathrm{native}}=y_j\},\qquad
R=2C-N_{\mathrm{answers}},\qquad U=R-C_{\mathrm{charged}}.
\]

`evidence/SCORING_REVIEW.json` reports **zero differences for all 2,560 native
runs**, including exact floating-point equality for utility, charged cost,
query cost and latency cost. Reward, correct-job count and completed-job count
also match exactly. Of 5,029 native answers, 30 have posterior exactly `0.5`;
all 30 native predictions are `1`, and their scores also match the published
result rows. No additional answers lie within `1e-12` of `0.5`.

This specifically closes the possible scoring discrepancy from using a Python
replay's answers in the experiment evaluator. It does not rely on that replay
to supply predictions or costs. The 640 separately labelled `fitted_dp` runs
are excluded because this review concerns actual native execution.

`evidence/SCORING_REVIEW_ROWS.json.gz` retains every row's original native
answers, evaluator labels, both score dictionaries, exact differences and
archive/stdout SHA identities. It is 270,280 bytes. Review computation used
2.794281 parent CPU seconds and 2.801580 wall seconds; those timings end before
final report serialization/compression. No new native execution or training
was performed. The completed experiment and its frozen source remain unchanged.

## Reproduce

Run from the repository root with a verified binary and a fresh output path:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.calibrated_operator_r11_20261031.audit.causal \
  --binary /tmp/hcsn-r11-native-build02/target/debug/codex-calibrated-operator \
  --build-report tools/hcsn/calibrated_operator_r11_20261031/evidence/BUILD_02.json \
  --freeze tools/hcsn/calibrated_operator_r11_20261031/evidence/training_02/FREEZE.json \
  --freeze-sha256 179037fca15a4f1ff5f08a50fd7c306b6ef5fdca82c6e951caa4091e293cbb20 \
  --policy tools/hcsn/calibrated_operator_r11_20261031/evidence/training_02/models/seed81031_analytic_value.json \
  --content tools/hcsn/round9_20261031/native/fixtures/fullhx.json \
  --public tools/hcsn/calibrated_operator_r11_20261031/evidence/smoke_01/input/train_seed81031_0000/native_public.json \
  --fixture-archive tools/hcsn/calibrated_operator_r11_20261031/evidence/training_01/data/development_seed81031.tar.gz \
  --output /tmp/r11-native-causal-audit
```

To independently score an already completed confirmation:

```bash
python -m tools.hcsn.calibrated_operator_r11_20261031.audit.scoring \
  --confirmation tools/hcsn/calibrated_operator_r11_20261031/evidence/confirmation_02 \
  --training-freeze tools/hcsn/calibrated_operator_r11_20261031/evidence/training_02/FREEZE.json \
  --output /tmp/SCORING_REVIEW.json
```

The output directory and JSON receipts use exclusive creation. Failed checks
produce a retained `SUMMARY.json` with traceback and partial findings instead
of overwriting an earlier successful or failed record.
