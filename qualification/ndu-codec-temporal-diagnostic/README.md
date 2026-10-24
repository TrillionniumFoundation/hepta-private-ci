# Retained codec temporal diagnostic

This is an exploratory diagnostic of retained local TAESD outputs, not a new
model run, prospective efficacy experiment, semantic audio/video benchmark or
replacement for the blocked private AV experiment. No new media was downloaded.
No original experiment result or acceptance criterion is changed.

The original `natural_io/codec_smoke.py` reports mean absolute adjacent-frame
difference. That is a valid motion-magnitude statistic, but reversing frame order
preserves it. New `temporal_diagnostics` reports reference-aligned frame MAE and
ordered delta residual, with per-interval values, while retaining both motion
magnitudes. It rejects invalid/mismatched timestamp grids rather than aligning
them implicitly. None of these metrics is an acceptance gate.

## Observations, including adverse control

The source identity, source reversed, source frozen, codec ordered, codec reversed
and codec frozen arms all remain in results.json. Codec ordered delta MAE is
0.09805703964, reversed 0.10987272413, but frozen is **0.07959923061**, lower than
the ordered codec. This is a critical counterexample to interpreting even the
new residual alone as temporal correctness or model quality. The source identity
residual is zero, and reversing the original source changes it to 0.11757169778
while its motion magnitude remains exactly 0.07959923061.

## Identity and time

Every input/codec artifact listed in the retained ingestion/codec receipts is
size/hash-verified before measurement. Input tensors are redecoded from the
existing four-frame WebM with the original RGB conversion and match exactly.
FFprobe decoded-frame best-effort presentation timestamps are 0,1,2,3 seconds
in both the input derivative and output export; PTS/DTS observations are retained.
The existing codec processes tensor indices in order and exports numbered PNGs
at 1 fps. This diagnosis compares raw pre-display codec tensors; the output WebM
timestamp check does not assert its decoded pixels equal those float tensors.
We do not sort packet order or invent source timestamps. The original ingest
uses seek 1 second plus fps=1 on a four-second window. Derivative timestamps are
not proof of exact source-frame capture instants or audio alignment.

## Cost boundary

The historical ten encode/decode forwards sum to 350 Conv2d calls,
37,079,285,760 MACs and 61,198,848 bias adds, exactly matching the historical
total. This is receipt arithmetic, not a new hook measurement. The original
scope excludes activations, resize, residual adds and memory operations; it is
not total FLOPs, energy or end-to-end physical cost. This run performs zero
model forwards. New wall/parent CPU/child CPU deltas measure only this diagnostic
after imports, including input hashing, FFprobe and reference decoding.

## Reproduce locally

The eight unit tests require only Python and NumPy and no original artifacts.
From this directory run `python -m unittest discover -s . -v`. For the actual
six-arm replay, also provide FFmpeg/FFprobe and retained original artifacts, then
run `python run_diagnostic.py RETAINED_RUN_DIRECTORY`.
The retained run must provide ingestion-fresh.json and codec-fresh.json with
their original artifact locations. Raw media, tensors and model weights are not
included in this evidence package. Inputs remain read-only.

The recorded source is “Lachender Hans (Tierpark Zittau).webm” by Fiver, der
Hellseher, CC-BY-SA-4.0, source SHA256
bc957c8a0382d9a4d2d54acbfc61c61e5fd57bcef909364bad3f41a5957c91ef.
Full existing attribution remains beside retained media; no endorsement implied.
Source page: https://commons.wikimedia.org/wiki/File:Lachender_Hans_(Tierpark_Zittau).webm
License: https://creativecommons.org/licenses/by-sa/4.0/

This is a new independent qualification directory on the same-topic #3610
base d847bb289159d8857f53cdcf5de79636e18df105, not a modification of natural_io.
Local original source bytes match the original execution receipts (see
provenance.json), but their upstream Git commit could not be located.
The base and #3563 do not contain that codec source. No origin commit or
remote availability of original inputs is claimed. Independent review replayed
the measurements and checked the arithmetic; hosted CI is not required or
claimed for this local diagnostic. No scientific or production qualification
is promoted.
