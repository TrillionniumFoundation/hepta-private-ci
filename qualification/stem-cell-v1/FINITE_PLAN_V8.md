# Physical Stem execution and finite-reuse Cell compute planning

Continuation of Draft PR #1654 from `b0f91cce9d7f9e18a19972ab353067de72ae86b9`.
Existing qualification directory and CI only. No new production runtime, store,
model-selection authority, live topology mutation or deployment is introduced.

## Close observed execution failures before claiming learning results

The old source-head/merge lane failed because safetensors.torch imports packaging,
which was absent from the isolated environment. Commit `eaf10d681c60da9c083644bc125107d26f1d6f70`
adds packaging 25.0 in all three environments and a real save/load tensor roundtrip.
Its exact workflow 38320655571 passed both complete-source mechanism jobs and the
historical-feature fitting/replay job. Its BGE task downloaded the fixed public
weights successfully but then FAILED exact state_dict/safetensors comparison.
The original failure artifacts are retained; this was not a network failure.

The fixed BGE source contains `embeddings.position_ids`, while Transformers
4.57.3 constructs that deterministic buffer with persistent=False. The opt-in
`bge-pinned-position-buffer-v1` staging recipe accepts only the registered source
weight SHA, exactly one inventory difference with that name, and int64 [1,512]
values identical to both arange(512) and the native runtime buffer. Every learned
tensor must match name, shape, dtype and value. The original publisher files stay
unchanged in publisher-model; model is a separately hashed derived snapshot.
The generic FrozenLocalHfBackend and exact materialization checker are UNCHANGED.
Both source and derived native models must produce bit-exact outputs on two fixed
label-free inputs, and the derived snapshot must pass zero-discrepancy loading
plus all-tensor verification. Unknown/missing/nonfinite tensors and modified
buffer values remain failures. No generic ignore option or pickle path exists.

Primary implementation reference: Transformers v4.57.3,
`src/transformers/models/bert/modeling_bert.py`, BertEmbeddings (position_ids and
token_type_ids registered nonpersistently). Exact public model revision remains
`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.

### Observed real pretrained result

At `1b387126288681eec2707b0a4e72ab3f5788b099`, workflow **38321714918** completed
all four jobs successfully: source, merge, historical features, and actual public
BGE execution. Public artifact **11779113101**, ZIP SHA256
`51e7c30f5feeaa0fc9990a9c0e3d79b267d23ad5b20308724f1621a22954af7e`,
contains the original source, publisher lineage, 199 verified learned tensors /
33,360,000 parameters, new Encoder forwards, fitted Heads and independent replay.
The derived weight SHA is
`ea1d11a3f23d14fe09fc1826fc7944e89c09a634d2217d57a21dd136805ee3e8`.

Eight-intent derived CLINC partition: 319 base / 240 adapt / 240 extra /
161 calibration / 240 held-out, retaining the contradictory duplicate group.
This is not unchanged official CLINC150 or prospective Hepta data. The same
existing mean-pooling recipe is used, not a published BGE leaderboard claim.

| Arm | Held-out correct | Brier |
| --- | ---: | ---: |
| frozen | 235/240 | 0.02852377 |
| continued | 235/240 | 0.02881401 |
| wider | 234/240 | 0.02908111 |
| more_data | 235/240 | 0.02916559 |
| split | 236/240 | 0.02877334 |

Calibration retained frozen. Split-minus-control calibration means are zero;
no statistical split advantage is established. Do not select using the later
test score. Independent saved-tensor replay reproduces 1,200 held-out predictions
across five checkpoints with zero maximum logit error and zero argmax reversals;
161 calibration rows / 160 content groups reproduce the original selection.
These groups are not authenticated independent speakers. Subsequent source
changes need their own CI and must not borrow this exact-SHA result.

## Pay for a finite episode, not hypothetical infinite amortization

V7's bounded folding and matched-validation comparison are now brought forward
from the previously local patch. The strong active-only dense comparator stays.
`cell_execution_plan.py` adds a research cost profile over those FOUR equivalent
Head equations. Calibration performs all four methods on calibration features,
records all actual compile/warmup/measurement work, and uses the largest of four
observations as a per-pass estimate. That maximum is NOT a confidence bound.

Given a known finite pass count H (1..32), select a feasible method minimizing
`startup_ns + H * per_pass_ns`. Extra compiled matrices AND their index table
must fit an explicit 0..64 MiB budget. Zero disables persistent-for-the-episode
dense compilation, not ordinary scratch. The tiled path retains its separate
explicit forward-float bound; neither bound is total RSS. Calibration itself
can need the larger comparison envelope and is charged separately, once.

The execution validates bank parameters, generation, Cell identities/awake state,
caller scope, exact request layout, precision, thread/runtime and source profile.
Only the chosen path is invoked after selection. Dense matrices are compiled
once for that episode and retained nowhere afterward. Errors do not trigger a
silent retry or a made-up success. Copies, binding checks, compilation, warmup,
actual passes and total episode time are reported separately. Caller hashes are
not authenticated authority, and clock/hardware attestation is not implemented.
The profile does not detect every hardware/frequency/load change; estimates may
underpredict. This is a deterministic finite-work cost special case, NOT a full
NDU/FBSDE solver, reasoning-depth policy or production Owner integration.

`cell_execution_plan_study.py` writes all six choices (H=1/4/16, extra budget
0/64 MiB) before timing new-valued held-out features of the same layout. No task
labels enter compute selection. Repeated passes are work probes, not additional
reasoning or independent outcomes. Existing multicell CLI opts in with
`--planned-serving`; the ordinary defaults remain unchanged.

### Observed local finite-plan study

Four actually trained Cells, 32 distinct input rows / 128 requests per pass;
PyTorch 2.10 CPU, two threads. Calibration cost was 28.383 ms, charged once.
Zero compiled storage selected shared; allowing storage selected active dense
(30,768 bytes). Episode totals, including common checking/copying, were:

| Passes | Shared, no extra compiled storage | Selected dense |
| --- | ---: | ---: |
| 1 | 2.928 ms | 2.453 ms |
| 4 | 6.067 ms | 5.189 ms |
| 16 | 20.456 ms | 20.747 ms |

The 16-pass dense episode was NOT faster, despite its lower estimate. No
unconditional speed/optimality claim follows. Output error stayed <=5.723e-6
with zero argmax reversals. Parent/Cell weights and quality stayed unchanged;
all four still achieved 118/120 on the historical four-intent test task.
The initial malformed 65-character study-scope value failed validation; that
failed attempt is retained, fixed to a real SHA256, and covered by full study tests.

The local qualification source was restored from the authenticated hosted source
archive. model_runner and study are now COMPLETE original files, not function
extracts. Local tests still do not compile the full Rust monorepo. New physical
BGE results above are hosted execution, not a claim of local model downloading.
Source-head/merge, global/native/security, independent future NDU and modality
quality remain distinct acceptance requirements. No general 10T/100T equivalence.
