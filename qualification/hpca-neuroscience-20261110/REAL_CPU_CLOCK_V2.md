# HPCA V2 — real CPU LoRA clock pairing, exposed evaluation only

**Research evidence (2026-11-11 UTC): HOLD_NO_GO / DENY_ALL.** This is actual
pretrained-model optimization on disclosed yes/no prompts, not a simulated
training trace, but **not** independent task efficacy, owner-authorized update
or production qualification. Do not merge/deploy or select these adapters.

## Why this experiment is distinct

The initial V1 real CPU run (#5861/#5881) gave the early/late LoRA groups
6/6 versus 9/3 opportunities and always ran uniform first. This new V2
executes the **pre-specified #5899 interleaved vs bursty** comparison, with
6/6 group updates in each arm, *identical ordered training record identities,
source SHA-256 and token counts within each group*, and two AB / two BA run
orders. The V2 experiment does not claim to isolate the seven Hepta cell
lineages. Group contents may coincide across groups. The fixed schedule
changes when optimizer updates occur, and does not equalize all hardware
effects, convergence trajectories or marginal runtime costs.

SmolLM2-135M-Instruct, CPU float32, pretrained frozen base, rank-4 q_proj
LoRA (138,240 trainable parameters, split 69,120/69,120), AdamW LR 0.001;
four paired seeds 11/17/23/29; 8 real training runs, 12 steps each, 96
actual optimizer steps total. No network dataset queries, GPU, Colab or
Kaggle used. Training fixture and B prompts were previously publicly
exposed; C contains eight operator-written yes/no prompts. B and C are
**not independent prospective evaluation tasks**.

| Measure | Interleaved | Bursty |
|---|---|---|
| Exposed B accuracy, seeds 11/17/23/29 | 3/4, 2/4, 3/4, 2/4 | 3/4, 2/4, 3/4, 2/4 |
| Operator C accuracy, all seeds | 3/8 | 3/8 |
| Train input tokens (four arms each) | 1,034 | 1,034 |
| Parameter-element optimizer updates | 3,317,760 | 3,317,760 |
| Sum arm wall time | 9.709457 s | 9.719076 s |
| Sum arm process CPU | 34.112922 s | 34.142241 s |

Frozen base B=3/4, C=3/8. Paired bursty-minus-interleaved B and C
accuracy differences are zero for each of four seeds; two seeds achieve
2/4 B, below base 3/4. This small, exposed evaluation **does not prove
statistical equivalence** and supports no timing-effect improvement claim.
Both arms satisfy matched source/optimizer opportunity preflight; neither
has independent task efficacy. These measured times exclude unmeasured
external opportunity and energy costs. Host caching, thermal/parallel
effects, power consumption and failed-attempt budgets are not controlled.

## Authoritative executable and raw evidence

- Parent/source clock V2 plan: #5899 Git SHA
  `ba243385e821f5722612ffb7129d479c49d34c17`.
- Actual host: authenticated heptaruntime `ai395`; original durable
  model-training job `1a1c87b36af-135c4-9b`, **exit 0** with complete
  stdout and no stderr. Separate exact output verification job
  `1a1c87cf3c2-135c4-9f`, **exit 0**.
- V2 training script SHA-256:
  `4dded105ac0477c9747b13d98ee1b57d46dcc322d034121a55a9c63a12250e5e`.
- Frozen clock module SHA-256:
  `dea150ee0083f792df4511c2b834cc4bb2f82b59819fa79ebdb373294cc0f880`.
- Raw `real_cpu_clock_v2_RESULT.json` SHA-256:
  `9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c`.
- Raw `real_cpu_clock_v2_PLAN.json` SHA-256:
  `08677c300eff2e66807b19529728dbf9b7b1e8bd43fa265949763261f7bca6af`.
- Local independent reader checks paired order and every per-group training
  tuple, plan digest, actual step log, B/C row arithmetic, candidate checkpoint
  hashes declaration, cold model-file reload probabilities, CPU/wall and
  parameter-update totals. GitHub CI reads the archived JSON; it does not
  rerun Torch. Original eight LoRA adapter artifacts remain on `ai395`
  in the frozen run folder, not in GitHub.

## Qualification

**HOLD_NO_GO / DENY_ALL**: the script uses the exposed training/B/C
fixture, self-declared dataset and model digests, and locally generated
timing/IO records. No independent evaluator or original StageOwner
signature authenticates them. Nothing here proves real ACT/CTRL task
completion, sparse/dense delayed credit, MEM typed replay/delete/old
retention, seven-lineage clocks, Core×NDU 2×2, independent B/C,
NoUpdate/Adopt, next-task FinalUse or actual owner cold recovery. New
scheduled proposals must remain review-only; do not promote checkpoint
weights, change production permissions, or declare a scientific effect.
