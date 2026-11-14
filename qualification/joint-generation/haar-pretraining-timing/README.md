# Fixed Haar pretraining timing: both strong-control gates fail

**HH−RR:0/8; HH−RH:0/8. All16 required comparisons fail; overall false.**
HH−RR CE improves in seven strata and decreases in one, with maximum gain about
.003954, below the unchanged .005 threshold. HH−RH CE improves in four and
worsens in four (approximately −.004863 to +.001088). Thus earlier Haar source-CE
pretraining does not satisfy the prespecified requirements against both strong A
controls. The prerequisite for a subsequent N experiment is not met: no N extension,
learning-rate search, basis sweep or threshold relaxation is undertaken here.
The tested timing extension is closed, not all possible coordinate optimizations.

RR means500 supervised source-CE steps raw, then300 A adaptation raw; RH shares
the same raw pretrained base and converts only for300 A adaptation; HH converts
before500 source-CE steps and stays Haar for300 A adaptation. Both coordinates
start from the same function by xH/H^T W, not identical numerical encoder weights
under different inputs. Same parameter count/function class and fixed Haar basis.
All adaptation paths reset Adam. Original A+ordinary aligned anchor .2, learning
rate .003, fixed data/batches, FIT-only temperature calibration, coupled serving
and all five quality gates remain unchanged. This is not a new NDU objective,
not a train/serve law fix and not evidence of NDU improvement.

Four shared decoder owners each train300 steps once. Their exact decoder tensors
are copied to eight raw/Haar content bases, each trained500 CE steps with identical
paired data/RNG; twelve clones then train300 A steps. Every input/conversion does
the same transform auxiliary work and selects/discards by coordinate. Raw prep
serves two control paths: global raw/Haar WORK therefore differs. Each standalone
path logically has300decoder+500CE+300A, but HH is NOT claimed CPU-identical to an
amortized control. Shared raw prep/decoder cost is not charged twice or called free.
Matched auxiliary work is not natural deployment timing. Adam is not generally
rotation covariant, and function equality at initialization does not imply equal
training trajectories or better generation.

Four old raw bases and eight RR/RH final models, all old full metrics/FIT records/
profile keys/datasets reproduce exactly. Initial and adaptation boundaries pass
fixed whole-FIT1e-12 engineering admission; no postresult tolerance adjustment.
All12 models then24 calibrated heads froze before known heldout noise regeneration.
Original TEST/VAL remain closed; already studied catalog/noises are not fresh global
holdout evidence. No selection among seeds, subgroups or pooled outcomes.

## Prespecified primary comparisons
Partial-command macro(full,low) calibrated CE and MSE differences:

| Contrast | Fold | Seed | Noise | CE change | Pixel MSE change | Pass |
|---|---:|---:|---:|---:|---:|---|
| HH_minus_RR | 0 | 103 | 3701 | +0.001667090 | -0.000045896 | False |
| HH_minus_RR | 0 | 103 | 3702 | +0.001919206 | -0.000048845 | False |
| HH_minus_RH | 0 | 103 | 3701 | +0.000163643 | -0.000019237 | False |
| HH_minus_RH | 0 | 103 | 3702 | -0.000374171 | -0.000022707 | False |
| HH_minus_RR | 0 | 107 | 3701 | +0.003560997 | -0.000082635 | False |
| HH_minus_RR | 0 | 107 | 3702 | -0.003533210 | +0.000084047 | False |
| HH_minus_RH | 0 | 107 | 3701 | +0.000745194 | -0.000018194 | False |
| HH_minus_RH | 0 | 107 | 3702 | -0.004862533 | +0.000103973 | False |
| HH_minus_RR | 1 | 103 | 3711 | +0.001752328 | -0.000045678 | False |
| HH_minus_RR | 1 | 103 | 3712 | +0.001509618 | -0.000040900 | False |
| HH_minus_RH | 1 | 103 | 3711 | +0.000239329 | -0.000013750 | False |
| HH_minus_RH | 1 | 103 | 3712 | -0.000617638 | -0.000009381 | False |
| HH_minus_RR | 1 | 107 | 3711 | +0.003954458 | -0.000112035 | False |
| HH_minus_RR | 1 | 107 | 3712 | +0.003250370 | -0.000076088 | False |
| HH_minus_RH | 1 | 107 | 3711 | -0.000821579 | -0.000019230 | False |
| HH_minus_RH | 1 | 107 | 3712 | +0.001087538 | -0.000034863 | False |

SUMMARY preserves all72 contrasts: two primary claims, unchanged RH−RR control,
and three self-calibration claims, each across4 cells×2noise plus pooled. All11
metrics/full-low-macro/all-partial and eight base evaluations remain complete.
Historical fullfactor reference remains descriptive only, not a concurrent fair
arm, model-selection device or scientific failure rescue.

## Full actual costs and accounting
50 literal tests passed;54 toy initializations,22 toy Adam updates,4 manual SGD
parameter steps are inside child costs. Single completely waited scientific child:
24.334163 CPU s,24.457967468 wall s,95108KiB RSS. Fixed limits30CPU/90wall/512MiB/
4MiB, CPU0/single thread/original shared lock/no retry. No resource extension.
1200 decoder,4000 supervised,3600 adaptation updates;18928 forwards/1334240rows.
Boundary work64 forwards/49920rows. Decode1212 calls/14544images comprises four
fits at301 calls each plus eight observer decodes, not eight decoder retrainings.
Raw aggregate8 encoder transforms/256columnrows and8848input transforms/613120rows;
Haar12 encoder transforms/384columnrows and10072input transforms/714880rows.
Every unique base's preparation and each adaptation is separately timed, alongside
shared decoder, conversion, boundary, FIT, serving, phase WORK and whole SHA counts.
24heads×28=672 NLL evaluations;64 evaluation serving calls/99840joint tables.
Prior Haar qualification .199515 CPU s and Haar-A13.450576 CPU s are additional;
other inherited costs and unknown preparation/review cost are not zero. Equal
logical updates or auxiliary operations do not establish equal CPU/wall costs.

## Portable six-file package
Exact timing helper/test and frozen PLAN accompany README, full SUMMARY and
VALIDATION. Required companion matched_haar/haar_coordinate/source_scene/model/
utility and aligned/grouped helpers and literal test dependencies must be available
on Pythonpath. This does not claim local/pending dependencies are published.
No unrestricted runner, weights, private inputs, runtime paths or remote operation
is included. Independent saved review validates execution/accounting, not the failed
scientific claim. Remote publication approval remains a separate matter.


## Lossless evidence storage

The complete original SUMMARY is stored as `SUMMARY.json.gz` to meet the repository blob limit. No metric or failed gate was removed. From `qualification/joint-generation`, run `python3 restore_evidence.py` to verify all four compressed summaries, or `python3 restore_evidence.py --output /path/to/new-output-directory` to restore exact original JSON files. The output directory must not already exist. `compressed-evidence-manifest.json` binds compressed and original SHA256 hashes and byte counts. This command verifies evidence only and does not run models or training. Old commit history remains unchanged.
