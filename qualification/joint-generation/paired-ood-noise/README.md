# Fixed paired corruption shift: limited Haar-A secondary positive; N primary fails

**Prespecified secondary HaarA−rawA passes8/8 original five-gate comparisons in
fixed sigma.35 OOD. All N primary conjunctions and originalID overall remain false.**
OOD HaarA−rawA CE gains range+.005616647 to+.015870763 and all required nonregression
gates pass. The same contrast in freshID passes0/8 (CE7 positive,1 negative).
This positive is a predeclared SECONDARY coordinate-A control, not the NDU primary,
not recovery of the original failed goal, and not evidence of new-group or natural
image generalization. No sigma/severity, seed, basis, learning-rate or threshold
search was performed, and the positive is not a guarantee of risk-aversion benefit.

OOD HaarN−HaarA worsens CE, text mass and joint success in all8 strata; MSE worsens
in seven and improves in one. HaarN−rawA passes3/8 and HaarN−rawN6/8, neither
satisfying its required8/8 conjunction. FreshID N gates also fail. The originalID
108 contrasts and12 interactions reproduce exactly, preserving its failed overall
criterion. No pooled, mixed-domain or secondary-control rescue of any primary gate.

## Fixed experiment and information boundary
The exact old4 shared bases/16 raw-or-Haar × A-or-original-rowN models were rebuilt,
with original300decoder/500sourceCE/300adapt updates, static grouped64 schedule,
rho1.5, learning rate .003 and ordinary aligned anchor .2. All16 models and32 old
FIT-only temperature heads freeze; complete oldID metrics/profiles/datasets and
model digests must match before generating paired real images. No weights restored,
OOD fitting, model update or recalibration. Original independent-training versus
coupled-serving law mismatch remains; no objective or numerical guard was changed.

Fixed noise seeds4701/4702 forfold0 and4711/4712 forfold1. For each of130 known
heldout catalog groups×6variants, one source scene render and common standard
Gaussian Z generate freshID=clip(clean+sigma_ID*Z) with sigma_ID uniform(.03,.25),
and OOD=clip(clean+.35*Z). Both retain the original full/low thumbnail recipe,
commands and labels. Only observed202 input features reach the model, never sigma,
seed, scene/group ID or renderer metadata. Sharing Z controls corruption direction,
not all clipping-induced effects. Gaussian/clipped input supports overlap: OOD
means corruption-regime distribution shift, not disjoint support or an asserted
invariant-P(y|x) covariate-shift assumption. This is the same known catalog/groups,
not globally blind data or natural-image evidence. Original TEST/VAL stay closed.

## Prespecified secondary coordinate-A results
Calibrated partial-command macro(full,low) differences; five-gate thresholds unchanged:

| Domain | Fold | Model seed | Noise | HaarA−rawA CE | Pixel MSE change | Pass |
|---|---:|---:|---:|---:|---:|---|
| freshID | 0 | 103 | 4701 | +0.003431740 | -0.000043666 | False |
| freshID | 0 | 103 | 4702 | +0.003832281 | -0.000058886 | False |
| freshID | 0 | 107 | 4701 | -0.000937434 | +0.000027677 | False |
| freshID | 0 | 107 | 4702 | +0.000493217 | -0.000020752 | False |
| freshID | 1 | 103 | 4711 | +0.001165466 | -0.000018492 | False |
| freshID | 1 | 103 | 4712 | +0.002769741 | -0.000039591 | False |
| freshID | 1 | 107 | 4711 | +0.003443563 | -0.000073099 | False |
| freshID | 1 | 107 | 4712 | +0.003550522 | -0.000064945 | False |
| OOD | 0 | 103 | 4701 | +0.005624018 | -0.000103742 | True |
| OOD | 0 | 103 | 4702 | +0.006902710 | -0.000127536 | True |
| OOD | 0 | 107 | 4701 | +0.005616647 | -0.000076648 | True |
| OOD | 0 | 107 | 4702 | +0.006076481 | -0.000100503 | True |
| OOD | 1 | 103 | 4711 | +0.006139030 | -0.000202581 | True |
| OOD | 1 | 103 | 4712 | +0.014466127 | -0.000272956 | True |
| OOD | 1 | 107 | 4711 | +0.010137088 | -0.000267422 | True |
| OOD | 1 | 107 | 4712 | +0.015870763 | -0.000296822 | True |

The complete SUMMARY preserves old108 contrasts+12 coordinate-objective DID,
freshID60 contrasts,OOD60 contrasts and60 paired cross-domain DID records, all
11metrics/full-low-macro/all-partial/noise/pooled. Cross-domain DID is explicitly
gate=null, not a new success criterion or general causal proof. Each domain reports
three N primary claims with8 required unpooled passes separately; the positive
HaarA control is not promoted to a primary after seeing results. Independent fixed
replication of this secondary finding would require a new prospective protocol;
it has not been performed or selected here.

## Full measured cost and validation
Single completely waited child34.204792 CPU s,34.370598453wall s,132236KiB RSS,
under40CPU/120wall/512MiB/4MiB, CPU0/singlethread/original lock/no retry.51 literal
tests passed,43 toy initializations/12 toy Adam updates/4 manual SGD parameter steps,
all included. New fixtures use only small handclean/Z, not actual evaluation data.

Original training/ID costs are not free and fully retained. Extra paired generation:
3120renders,3120 uniform sigma draws,599040 standard-normal scalars,6240 clipped
images,6240 thumbnails and12480 full-low rows. Saved sigma/Z/render/input hashes,
manifest and whole-child SHA work bind these data without publishing payloads.
Extra64 model forwards/99840rows and64 calibrated serving calls/99840tables;
combined18576 forwards/1396000rows and136 serves/212160tables. Each coordinate
adds32input transforms/49920rows; no new decoder fitting, NLL fitting or training.
384 additional metric reductions, exact row/attribute visits and60 scalar paired
DID records are charged. Per-domain/per-model evaluation and serving CPU, generation
CPU, contrast-reduction CPU and all phase counters/barriers are retained.
Prior2x2 study24.903823CPU and qualification/preparation costs remain additional,
unknown review/preparation time is not zero. Matched auxiliary transforms are not
natural deployment cost; equal operations need not imply equal CPU/wall time.

## Portable six files
Exact paired_corruption.py/test_paired_corruption.py/frozen PLAN, this README,
full SUMMARY and VALIDATION only. Companion original data/group_data/NumPy modules
are required for the separately controlled science endpoint; the literal tests do
not import those data modules. This package does not assert pending companion
artifacts are published. No unrestricted runner, model weights, private input,
runtime path, merge/deployment or remote write is included. Independent saved review
validates execution/accounting, not the failed NDU primary. Publication authorization
is separate and not implied by these local files.


## Lossless evidence storage

The complete original SUMMARY is stored as `SUMMARY.json.gz` to meet the repository blob limit. No metric or failed gate was removed. From `qualification/joint-generation`, run `python3 restore_evidence.py` to verify all four compressed summaries, or `python3 restore_evidence.py --output /path/to/new-output-directory` to restore exact original JSON files. The output directory must not already exist. `compressed-evidence-manifest.json` binds compressed and original SHA256 hashes and byte counts. This command verifies evidence only and does not run models or training. Old commit history remains unchanged.
