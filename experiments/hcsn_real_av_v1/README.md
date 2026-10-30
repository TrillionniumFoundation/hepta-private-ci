# Real paired audiovisual extension

This separately registered study uses original CREMA-D actor recordings. Audio
and video come from the same official hash-verified FLV, not an artificial
image/audio pairing. It tests six-class acted-emotion recognition and paired
clip retrieval on speakers absent from training and validation. It does not
claim natural-language understanding, unrestricted video understanding, full
multimodal generation or online/causal audio preprocessing.

`PROTOCOL.json` fixes 30 actor identities by a filename-only hash rule, four
sentences, six emotions and one intensity code. Twenty actors train, five select
checkpoints, and five form the heldout test. All 720 registered clips must be
present; a failed download or decode cannot silently remove a clip. There are
480/120/120 train/validation/test clips and no actor or clip overlap.

The low-level frontend has no learned pretrained component. Audio log-mel and
visual DCT features share the same original time interval, are resampled to 32
offline observations, and retain true elapsed duration. Training actors alone
set normalization. Every architecture receives the same tensors and timestamp
information. Separate audio and video encoders jointly learn contrastive
pairing and emotion classification. Within-actor retrieval controls for the
easier actor-identity matching shortcut. Deranged video controls preserve actor
identity but break exact recordings; unpaired effects remain descriptive.
The derangement can change both sentence and emotion, so a performance drop
does not by itself establish use of temporal synchronization.

The seven arms include three retained-distribution HCSN controls, ordinary dual
gates, a causal Transformer, LIF SNN and a CPU Mamba-1 reference. Model-width
matching uses the existing v2 backbone target. No optimized CUDA/neuromorphic
hardware comparison is implied. Three seeds and this small cohort cannot
establish general architecture superiority.
All fits spend the same 128-update training budget. Validation chooses a
checkpoint at update 32, 64 or 128, so the selected weights can have different
training exposure. Report that selected step and the cost of all 128 updates.

## Reproduction

Run from the repository root with NumPy, SciPy, CPU PyTorch 2.8 and ffmpeg.
Keep numerical-library thread counts at one. A sealed checkout includes the
portable tensor database and exact source/hash records. Verify it, then train
into a fresh result directory:

```bash
python -m experiments.hcsn_real_av_v1.audit verify
python -m experiments.hcsn_real_av_v1.study --model distribution_free_dual --seed 9301 --output /tmp/hcsn-real-av-new-run/distribution_free_dual-9301
```

To rebuild media/features independently, use a fresh output directory and compare
its split-array hashes with `data/DATASET.json`; do not replace the sealed data:

```bash
python -m experiments.hcsn_real_av_v1.data register --cache /tmp/hcsn-av --output /tmp/hcsn-av-rebuild
python -m experiments.hcsn_real_av_v1.data acquire --cache /tmp/hcsn-av --output /tmp/hcsn-av-rebuild
python -m experiments.hcsn_real_av_v1.data prepare --cache /tmp/hcsn-av --output /tmp/hcsn-av-rebuild
python -m experiments.hcsn_real_av_v1.audit data --cache /tmp/hcsn-av --output /tmp/hcsn-av-data-audit.json
python -m experiments.hcsn_real_av_v1.audit preflight --output /tmp/hcsn-av-preflight.json
```

The trainer requires a complete `FREEZE.json` binding sources, protocol,
normalization and split arrays. Freeze and publish those identities before
running any heldout scoring. The original registration used `audit data`,
`audit preflight`, then `audit freeze` before publication; immutable receipts
are retained. A new execution requires a fresh output directory.
The selection lock is written after all fixed-update candidates finish and
before the test NPZ is loaded. Numeric checkpoints and all training minibatch
indices are retained. Failed jobs retain failure receipts rather than being
removed from the comparison. Training CPU is nested within process CPU; do not
add these overlapping costs. Interpreter startup belongs in an outer worker
receipt if full process-launch costs are being compared.

The original v2 probability kernel is bound by hash. Every HCSN forward checks
all 32 observations for finite, nonnegative probabilities and maximum mass
error at most 1e-4. The train-only preflight uses the eight longest training
clips and verifies connected gradients and actual updates in every parameter
group. Its disposable models never become training checkpoints. Data checks
inspect fixed schemas, identities and normalization; they do not score models.
Feature-preparation CPU includes decoder subprocesses and is reported separately.
Download costs and interpreter-import costs are not measured by that receipt.

For review, acquisition/decoding and its data integrity audit form one coherent
stage; the registered two-encoder trainer and train-only integration gate form
the next. Both must be sealed before this study is scored.

## Attribution and database license

CREMA-D was created by Houwei Cao, David G. Cooper, Michael K. Keutmann,
Ruben C. Gur, Ani Nenkova and Ragini Verma. Citation: *CREMA-D: Crowd-sourced
Emotional Multimodal Actors Dataset*, IEEE Transactions on Affective Computing
5(4), 377–390 (2014), DOI 10.1109/TAFFC.2014.2336244.

Official source: https://github.com/CheyneyComputerScience/CREMA-D , pinned at
`1658cd342dff90010aa843eaeebd53610a08b1dc`. The database is offered under
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1.0/) and individual contents
under [DbCL 1.0](https://opendatacommons.org/licenses/dbcl/1.0/). The original
declaration is preserved as `data/CREMA_D_LICENSE.txt`. This selected and
transformed tensor database is distributed under the same ODbL/DbCL terms;
retain its attribution, source manifest, licenses and reproducible derivation.
This notice concerns the database; new research code follows the repository's
code license. Actor IDs are official recording identifiers. No demographic
inference or identity-recognition objective is used.
