# Prospective fixed-corruption replication: Haar-A passes the OOD primary

**Primary OOD HaarA−rawA:8/8 original five-gate comparisons pass. FreshID:2/8;
its all-eight conjunction fails. Prior originalID and NDU goals remain false.**
In fixed sigma.35 OOD, CE gains range+.0077721905 to+.0308561736; all four required
nonregression metrics strictly improve in all eight strata. FreshID CE improves in
all eight, but six fail the unchanged .005 CE threshold; the other nonregression
gates pass (one greedy-text delta is zero). No threshold, seed or severity rescue.

The prior finding was a prespecified SECONDARY control with8/8 OOD passes; this
new protocol prospectively made the SAME comparison primary, then fixed new model
seeds109/113 and paired-noise6701/6702/6711/6712 before execution. It did not
retroactively promote the old result. These are not16 independent source groups:
the same catalog/groups and FIT corruption streams are reused, with new model
initializations and paired evaluation corruptions. No natural-image, globally blind
new-group or NDU-training benefit claim follows. OriginalID/N primary failures
remain explicit and cannot be rescued by this limited A-coordinate result.

## What changed, and what did not
Four new raw Source bases train300 decoder+500 source-CE steps, then yield raw/Haar
fresh-moment clones for300 A+ordinary aligned anchor.2 updates. Same fixed static
grouped64 sampler,learning rate .003, qualified decoder/serving and FIT-only
calibration algorithm. Haar is applied only at adaptation boundary, not pretraining.
It retains all192 coordinates and is orthogonal/invertible: NOT a denoiser or a
high-frequency deletion. Initial xH/H^T W preserves function up to fixed numerical
admission; diagonal Adam can follow a different learned trajectory. Auxiliary raw
transform work is discarded for work matching, not a natural deployment benchmark.

The observed contrast is the trained-coordinate PLUS common FIT-only-calibration
procedure. Fitted scalar temperatures may differ by model. Calibrated-only evaluation
cannot isolate CE/MSE contributions from training versus calibration. Runtime
argmax-preservation checks ensure positive-temperature calibration did not change
each model's greedy output: the strict OOD greedy-text improvements cannot be
attributed only to that calibration. This narrower fact does not remove calibration
mediation for CE or MSE or establish that the fixed transform itself removes noise.

All8 new models then16 old-FIT-only calibrated heads freeze before actual670x data.
Each paired source render shares Gaussian Z between freshID sigma uniform(.03,.25)
and OOD sigma.35, followed by the original clip/full/thumbnail/instruction recipe.
Model inputs contain neither sigma/seed/group ID nor renderer metadata. This is a
corruption-regime shift, not disjoint input support or assumed invariant-P(y|x)
covariate shift. Only frozen calibrated adapted models are evaluated: no base,
uncalibrated or old370x evaluation, no OOD tuning or new training. TEST/VAL closed.
New seeds imply new expected weights; no old-digest reproduction or restoration
is falsely claimed. Old source laws and FIT manifests are bound unchanged.

## Complete fixed comparisons
Calibrated partial-command macro(full,low) HaarA−rawA differences:

| Domain | Fold | Model seed | Noise | CE change | Pixel MSE change | Pass |
|---|---:|---:|---:|---:|---:|---|
| freshID | 0 | 109 | 6701 | +0.002872371 | -0.000042695 | False |
| freshID | 0 | 109 | 6702 | +0.003892161 | -0.000045859 | False |
| freshID | 0 | 113 | 6701 | +0.000392952 | -0.000044725 | False |
| freshID | 0 | 113 | 6702 | +0.001443490 | -0.000052410 | False |
| freshID | 1 | 109 | 6711 | +0.007389831 | -0.000139088 | True |
| freshID | 1 | 109 | 6712 | +0.010494797 | -0.000206726 | True |
| freshID | 1 | 113 | 6711 | +0.000674224 | -0.000017862 | False |
| freshID | 1 | 113 | 6712 | +0.001111429 | -0.000010476 | False |
| OOD | 0 | 109 | 6701 | +0.012159714 | -0.000190325 | True |
| OOD | 0 | 109 | 6702 | +0.007772191 | -0.000099637 | True |
| OOD | 0 | 113 | 6701 | +0.012083160 | -0.000273196 | True |
| OOD | 0 | 113 | 6702 | +0.010111413 | -0.000285138 | True |
| OOD | 1 | 109 | 6711 | +0.030856174 | -0.000706586 | True |
| OOD | 1 | 109 | 6712 | +0.025325522 | -0.000603259 | True |
| OOD | 1 | 113 | 6711 | +0.012015850 | -0.000237512 | True |
| OOD | 1 | 113 | 6712 | +0.010036133 | -0.000214464 | True |

All24 contrasts (12/domain including pooled),12 paired domain DID with gate=null,
all11metrics/full-low-macro/all-partial, profiles, model/base digests, latent hashes,
dataset manifests and freeze barriers remain in SUMMARY. Primary acceptance is
only the eight unpooled OOD original gates, not pooled or subgroup significance.
No claim that these finite correlated comparisons are a population significance
test. FreshID remains separately reported, and old secondary/negative history stays
visible. No additional seeds or sigma sweep were added to obtain all passes.

## Actual complete costs
Single fully waited child14.132769 CPU s,14.209456495wall s,126100KiB RSS under
25CPU/90wall/512MiB/4MiB,CPU0/singlethread/original shared lock/no retry.51 literal
tests passed,37 toy initializations/12 toy Adam updates/4 manual SGD parameter steps,
all charged. Four shared bases/eight clones,1200decoder+2000supervised+2400adapt
updates.11272 forwards/797920rows include24 boundary forwards/18720rows,16FIT
forwards/12480rows and32paired forwards/49920rows.1208decode calls/14496images.
Each coordinate4encoder transforms/128columnrows and2432input transforms/191040rows.
16heads×28=448 NLL evaluations;32calibrated evaluation serves/49920tables, no
base-evaluation profile roundtrips. Same logical updates do not mean identical CPU.

Paired generation adds3120 renders/sigma draws,599040 standard-normal scalars,
6240 clipped images/thumbnails and12480 full-low rows.192 scalar metric reductions,
actual row/attribute visits,12paired DID, all sigma/Z/render/input SHA work and
per-domain/model serving/evaluation costs retained. Shared prep charged once;
conversion/boundary/calibration/array/manifest costs not free. Prior discovery
34.204792CPU and other qualification/review/preparation costs additional; unknown
cost is not zero. Public package construction does not perform scientific replay.

## Portable six files
Exact replication_paired_corruption.py/test_replication_paired_api.py/frozen PLAN,
README, full SUMMARY and VALIDATION. Companion paired_corruption.py (including
unchanged qualified paired_images), original data/group_data and NumPy are required
on Pythonpath. The one new API test never generates actual paired data; the exact
old47+paired3 tests remain qualification dependencies. Local/pending dependencies
are not claimed published. No unrestricted runner, weights, private inputs, runtime
paths, remote write, merge or deployment is included. Saved review validates the
execution and the precisely scoped primary, not the original failed NDU goal.
