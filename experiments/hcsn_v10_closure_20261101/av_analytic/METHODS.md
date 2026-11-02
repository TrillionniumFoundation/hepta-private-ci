# Historical AV latent-renewal candidate

This line adds the previously absent analytic candidate to the historical AV continuation-prediction interface. It uses the same frozen v3 content head, immutable accepted prefixes, request costs and value controller as the ordinary models. The data are previously exposed historical recordings, not the missing v6 protocol, strong head or independent new cohort.

## Candidate and exact scope

The learned state has 32 signed scalars, interpreted as sixteen content pairs. Before assimilating a newly accepted packet, five bounded parameters computed from the **previous** state specify a shared input-local Brownian first-passage/reset law. For source increment dt, the count tails are the original renewal expression with distance x+(n−1)reset and elapsed dt−(n−1)refractory. The implementation takes the probability-weighted rotation of each content pair over event counts, then assimilates the currently accepted features through learned drive/gain maps. Physics parameters, rotation angles, content assimilation and the continuation-correctness reader are optimized together.

The profile explicitly requires finite dt in [0,1]. Accepted source prefixes advance one step at a time; a second modality at the same global source time has dt=0 but still updates content. Refractory≥0.16 makes the tenth count tail zero in this profile; the code separately checks the tail rather than relying on renormalization. Negative, nonfinite or unsupported increments are rejected. Independent SciPy probabilities, count-law gradients, mean preservation and single-event support are checked.

This is a newly defined latent inductive bias with re-anchoring at accepted inputs. It is not an identified stochastic law of speech/video, a recovered v6 observation model, an exact continuous free-boundary neuron, or a proof that the signed memory state is the physical latent media state. The common content encoder/head remains frozen. Only the continuation model is jointly trained.

## Data and training

`interfaces.py` and the bounded full-history reference are attributed to the other v9 source tree, fixed at remote commit `03f338eb44bf585bfe9d4f87e4f5ef7af98884ad`; the Library archive carries a different local commit identity. `SOURCE_EXTRACTION.json` records the exact definitions and the intentional addition of raw accepted-packet diagnostics. The parent of this v10 work is the separate v9 branch at `8cc469fcb0e6527fac56e26b65baa3ae1c09c86b`.

The source archive provides training and validation tensors expanded over ten legal acquisition schedules per object. Those schedules are correlated repetitions, not independent recordings. Targets are the **actual correctness of the frozen common head** at each legal future cache endpoint; they are not a teacher posterior, teacher Q or hidden media-state label supplied at inference. Model inputs contain only accepted features, current common-head probabilities, current prefix levels and source increment. Future slots and labels are not supplied to the recurrent update or action reader.

Five seeds train each of direct-cache MLP, GRU, SSM, bounded complete-history MLP, full renewal, mean-preserving count reduction and at-most-one-transition reduction, for two tasks: 70 candidates. The reader target, optimizer, validation selection and maximum update rule are shared; parameter counts are reported, not asserted equal. Ordinary model family selection uses the historical validation BCE before this round's historical evaluation. The two analytic reductions are independently retrained; full-weight execution reductions are also evaluated. The complete-history reference stores 246 observation scalars plus six masks; its 32-value scheduler snapshot is a digest, not a compressed neural memory claim.

The initial common source split has 24 original audio recordings from four training actors and 12 from two validation actors. Binding creates paired objects from the same recordings; those pairs do not double the independent cohort. All splits, including the set named test, were used previously. Results are descriptive historical replay and do not receive fresh-confirmation confidence intervals.

## Retained failures and cheap reference

The first metered behavior run failed when a future-input mutation also changed source increments to an unsupported value. This exposed the missing explicit clock/support guard. The exact old source and failed receipt are retained. The corrected six-test suite preserves valid future clocks while mutating future content and separately rejects invalid clocks. No frozen successful PLAN or result was overwritten.

Training itself is not evidence that the selected model learned. In the emotion task, **34 of 35 candidates select epoch 0**, including all five full-renewal models with zero selected physics-parameter change. Their final weights were trained, but validation rejected those updates. Binding candidates select nonzero epochs; the five full-renewal physics maps change by about 0.04–0.046 in maximum absolute parameter value. These two outcomes must not be collapsed into “70 learned models.”

An independent, post-hoc train/validation diagnostic folds the ten schedules back to original recordings and actors. Emotion training masked correctness rate is 0.889506 versus 0.338580 in validation. A training-prior constant has validation BCE 1.496617, versus 0.693147 for the flat 0.5 constant. This supports investigating train-to-validation correctness-target shift; it does not by itself identify the causal reason for every selected initialization.

The additional constant-0.5 reference is motivated solely by that validation diagnostic. It has a separate protocol and cost account, does not replace the original frozen B, and is explicitly post-hoc to the initial experiment. Other processes may already have evaluated the historical test set. It is not described as a new pre-registered confirmation.

## Execution and reproducibility

The common historical executor admits actual prepared-prefix arrays and copies the requested rows. Source/service time is logical, with the inherited declared 1 ms/read; actual process CPU is measured separately. This line does not decode original media, rerun the historical acoustic/visual feature pipeline, measure GPU latency or device energy. Full input NPZs and common-head checkpoints are copied into `results/development001/assets/`, and training/validation tensors are stored per task. The candidate source and inputs are frozen in PLAN before training.

Use a Python environment with compatible Torch, NumPy and SciPy. This run used the read-only Torch 2.15.0+cpu runtime at `/tmp/hcsn-torch-runtime`; it was not installed or packaged as part of the research. Another environment should use its own installed compatible runtime. All formal phases are launched once by `../economics/stage_meter.py`; preparation, training, execution and audit receipts are separate, nested timers are not added again. Authoring, initial discovery and missing historical preparation costs remain unknown.

For fresh output, invoke `campaign prepare --output <new> --bundle <materialized-v9-archive-root>`, then `campaign train`, `campaign evaluate`, and `audit <new>`. The published output already includes the necessary prepared data and frozen heads; reproducing train/evaluate over that output does not require the original absolute recovery path, but new artifacts must use new paths to preserve frozen evidence. See the root reproduction guide for copying the frozen input set and preserving exclusive-write behavior.
