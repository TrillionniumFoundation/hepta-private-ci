# Trained shared serving and independently replayed structural decisions

Continuation on PR #1654, original head
`91a14af155800943d75317647520fcaf9ef3dcf1`. This change stays in the existing
qualification directory and CI. It does not add a runtime, durable store,
model selector, signing authority, production route or replacement trainer.

## A reproduced selection-integrity failure

The previous saved-tensor replay recomputed held-out predictions but did not
recompute calibration selection. In a copied synthetic run, changing the
selected arm from `frozen` to `continued`, setting split `stored_scalars` to
zero and consistently rehashing the selection/run still passed its replay.
The original predictions and checkpoint bytes were unchanged. This is an
arithmetic evidence gap, not an exploit against a production authority.

`development_selection_replay.py` now independently checks the saved tensors'
parameter digests/counts, registered rank, Cell identities, generation and
unchanged inherited basis/readout. It recomputes calibration logits, equal-source
weights, the four comparisons, Hoeffding radii, scalar penalties and tie order.
It imports neither the fitter nor its selection routine. Altering a winner,
parameter cost, group count, step count or bound and rehashing does not pass.
A supported synthetic positive split also passes: this is not a reject-all gate.

Calibration truth is used only to verify the original fixed decision. Held-out,
future and OOD truth never enters this calculation. Router fitting, optimizer
trajectories, independent source provenance, clocks and CPU costs are not
reproduced or authenticated. Consistent fabricated inputs still require external
execution evidence. No scientific or production acceptance follows from replay.
Nonfinite replay arithmetic is rejected, including overflow from finite operands.

## Measure the trained output, not only Encoder vectors

`development_serving_probe.py` loads the saved selected Head and normalizer once,
then uses the existing SharedStemEngine for three paths on the same resident
Encoder: serial/no-cache, serial/reuse, and batch/reuse. Each uses identical
label-free held-out inputs. Three balanced rotated trials give each path each
execution position once, with a fresh feature cache per trial. Kernel state can
already be warm from preceding study work; this is not a cold model-load test.

Timers include actual encoding/cache lookup, normalizer and trained Head math.
Checkpoint reading/hash verification and probe preparation are separately timed.
All encoded rows, backend invocations and Head-evaluated rows remain distinct.
Full batch time is recorded, not a timer started after the kernel. Final logits
must match to a predeclared absolute 1e-4 with no argmax reversals. The independent
saved-prediction replay keeps its original, stricter 1e-5 threshold.

Logical aliases share ONE selected Head; they are not claimed as independently
trained Cells or physical Encoder copies. Numeric tensor byte counts are not RSS.
The probe excludes native owner queues, final-use, WAL, energy and isolated
per-arm process residency. Timing repeats are not independent outcome samples.
It makes no resource/quality superiority or 421M replication comparison claim.

## Execution and scoring

The existing public-weight CLI now runs the trained probe after fitting, verifies
Encoder tensors/snapshot/data again, and writes run.v3 with the probe file SHA.
The replayer supports historical run.v2 inputs but returns a new replay.v2 result;
old replay successes are not automatically upgraded. For v3 it also checks probe
identity, complete trial census, output-error limits and internal work counts.
These are consistency checks, not host attestation.

Scoring calls numerical and selection replay before writing scores whenever
`seal_replay` was explicitly enabled. Private runs without feature-export opt-in
remain possible; their report explicitly says selection arithmetic was not
replayed. No private feature export is silently enabled. Existing source-head,
prospective-merge, public-pretrained and global CI gates are retained.

## Observed local evidence and outstanding real execution

106 explicit tests passed with no skips on Python 3.13.5 / Torch 2.10.0+cpu.
The local source is a partial checkout and still uses the inherited, labelled
`local_reference` function extracts for model_runner/study imports. Those files
are not submitted as repository replacements; hosted full-source CI is required.
A separate synthetic run saved nine trained-serving trials, replayed 160
predictions and eight calibration rows, then ran the separate scoring command.
Trained-serving logit error was zero. Per trial, 32 logical requests used 32/4/1
backend calls and 32/4/4 encoded rows respectively; every path evaluated 32 Head
rows. These counts exercise mechanisms, not real BGE throughput or learning.

The actual public staging command was attempted again and failed at DNS with
`httpx.ConnectError: [Errno -3] Temporary failure in name resolution`, before
pretrained weights or a successful stage.json. Original failure records are
retained. No random-weight substitution or loader relaxation was introduced.
Real pinned BGE/CLINC execution, native Worker/Cell CAS/WAL, independent future
NDU/retention evidence, four-modal generation and production qualification remain
unestablished by this change. Current exact-SHA CI must be read separately.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=qualification/stem-cell-v1 \
  python3 -m unittest -v test_shared_encoder_eviction development_tensor_checks \
  development_repository_checks development_study_checks public_structural_checks \
  selection_replay_checks serving_probe_checks
```
