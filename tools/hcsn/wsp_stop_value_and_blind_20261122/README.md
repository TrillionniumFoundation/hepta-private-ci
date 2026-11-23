# Stop and continuation edits on five trained Hepta checkpoints

These experiments reuse five 85→48→4 renewal-policy checkpoints from `def96748960a30eaf917bd43a368cfddddfd547f` and the immutable full-network BP comparator from the 2026-11-22 Hepta WSP evidence archive. The scientific comparison uses supplied finite task laws. The deployable weight decision is KEEP.

## One-dimensional weight edit

A single scalar shifts the three stored WAIT, READ and REPAIR output biases equally. The remaining 4,321 neural parameters and the analytic model stay fixed. Under ideal additive score arithmetic the best continuation competes with the best terminal action at one threshold per state. The hard policy is constant inside each open interval between successive thresholds. We computed exact expected task payoffs within each representable interval, compared the unchanged model, then replayed the selected stored binary64 biases on every training world. This enumerated 23,181 representable midpoints across five fits, out of 23,192 mathematical cells. The search excludes isolated boundary ties and makes no optimality claim outside this scalar family. Reversed displacements, a differentiable rollout objective with Adam on the same scalar (64 steps and fixed temperature 0.05), and existing full-network Adam distillation on the same 32 GEN worlds per fit provide controls. The direct and gradient methods optimize different hard and smooth objectives. The full-network model also differs in trainable support and training objective.

The candidates were sealed before 80 IID and 80 OOD world schedules were sampled. All 160 differ from 4,196 recorded historical schedules. Each candidate was scored from its own realized state occupancy, using the same complete graph in each paired comparison.

| Method | IID value | Change from KEEP | OOD value | Change from KEEP | World losses >0.05, IID / OOD |
| --- | ---: | ---: | ---: | ---: | ---: |
| KEEP | .206839 | 0 | .129847 | 0 | 0 / 0 |
| Direct scalar | .201303 | −.005535 | .133349 | +.003502 | 4 / 8 |
| Same-scalar Adam | .209744 | +.002906 | .114853 | −.014994 | 1 / 10 |
| Reversed direct shift | .210857 | +.004018 | .133404 | +.003557 | 0 / 4 |
| Full-network BP | .188193 | −.018646 | .103022 | −.026825 | 24 / 20 |

The direct edit improved mean GEN utility from .237747 to .246556 and improved all five individual fits on GEN. Its five-fit two-sided sign-flip comparisons against KEEP gave .1875 IID and .8125 OOD. Under sign symmetry these have limited resolution with five fits. One OOD world lost .381346 with direct editing. Fitting took 0.358 CPU seconds for the direct search and 0.580 for scalar Adam, in addition to 0.379 common CPU seconds. End-to-end measurement took 38.48 CPU seconds excluding historical training and graph/feature production. Independent BLAS scoring and forward payoff accumulation reproduced all 800 held-out values to 3.33e−16; 65 training graph curve cross-checks differed by at most 1.11e−16.

## Model-based action veto

A second study fixed the preceding weights, implementation and roles, then sampled 40 IID and 40 OOD worlds excluding all 4,356 prior schedule hashes. It tests an execution-graph intervention. For the incumbent policy π, its complete own-law return from action a is Qπ(s,a). The wrapper accepts a proposed action when its lower return bound exceeds the incumbent action's upper return bound by more than 1e−10. It obtains bounds by finite-horizon backward propagation with terminal rewards in [−1,1] and nonnegative known transition fees. The complete version computes Vπ and evaluates the candidate first action followed by π. At every changed state the accepted action improves Qπ. Backward induction then gives weak policy improvement for this supplied law. The unrestricted control chooses the best legal first action according to Qπ without editing any weights. The branch scorer reads policy, legal actions, task terminal payoffs and transition fees/probabilities. Scoring code separately computes optimal values for diagnostics.

| Wrapper / proposal | Mean change IID | Mean change OOD | Worlds improved / worsened out of 80 |
| --- | ---: | ---: | ---: |
| Direct scalar without veto | −.004786 | +.011959 | 23 / 7 |
| One-transition bounds | 0 | 0 | 0 / 0 |
| Two-transition bounds | +.002810 | +.013612 | 18 / 0 |
| Complete Vπ veto of direct scalar | +.005862 | +.014990 | 22 / 0 |
| Complete Vπ veto of reversed scalar | +.010864 | +.000371 | 7 / 0 |
| Best first action by Qπ | +.055642 | +.125206 | 60 / 0 |

The replay evaluated 640 policies on 37,333 states. Independent forward flow and backward payoff values agreed within 3.33e−16. The evaluator materialized complete graphs even for short lookahead. The 0.221 CPU seconds spent computing all veto policies excludes feature and graph construction; the overall study took 18.83 CPU seconds. These results describe a local simulator with a known law. Capability on trading data would require a matched independent deployment evaluation. A separate post hoc surcharge experiment doubles settlement fees while leaving the actor's observations and transitions unchanged. The complete veto of the direct shift then loses against the incumbent in one world (−.078118); the unrestricted planner loses in three (worst −.143844). The two-transition wrapper retained nonnegative deltas in these 80 schedules. No robust optimality follows from this finite stress test.

## Reproduction

The private dependency is the owner's previously delivered `Hepta_WSP_Evidence_20261122_ET.zip`, SHA-256 `8dff90e9af87e9c5dcfea9af47226856454d3bb449bef8fcb7b5dee865f4bc2b`. Extract its root without renaming its `neuron` and `fullbp` subdirectories. It contains original checkpoints and GEN inputs, archived comparator weights, evaluation modules and preceding schedule hashes. Only source and compact outcome records are included in the repository. Schedule and full row files are in the accompanying evidence package. The recording environment was Python 3.12, NumPy 2.3.5 and SciPy 1.17.0.

From this source directory, with the archive root in `HEPTA_WSP_INPUTS`, run the following in fresh output directories. The entropy arguments reproduce the measured schedules. Omitting them creates a new sample. Each verifier shares the upstream law and feature construction.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
study_seed=$(python -c 'import json; print(json.load(open("records/study/WORLDS_PIN.json"))["entropy"])')
veto_seed=$(python -c 'import json; print(json.load(open("records/veto/WORLDS_PIN.json"))["entropy"])')
python stop_bias.py "$HEPTA_WSP_INPUTS" fresh-study --entropy "$study_seed"
python verify_stop_bias.py "$HEPTA_WSP_INPUTS" fresh-study
mkdir veto-replay-input
cp records/study/FITS.json veto-replay-input/FITS.json
cp fresh-study/WORLDS.json veto-replay-input/WORLDS.json
python advantage_veto.py "$HEPTA_WSP_INPUTS" veto-replay-input fresh-veto --entropy "$veto_seed"
python fee_sensitivity.py fresh-veto/ROWS.json fresh-veto/FEE_SENSITIVITY.json
```

The veto schedule seed binds the complete original fitting receipt, including machine-specific timings. Its replay uses that retained receipt with the regenerated first-stage schedules. Each candidate is independently reconstructed against its canonical model digest. A fresh fitting receipt produces a different veto sample by design.

The initial dry attempt compared the archived comparator's compressed-file hash to its canonical-model hash and stopped before drawing entropy. The experiment then bound the decoded canonical model against its own recorded digest and also recorded the compressed-file hash. The retained receipt and script freeze refer to the corrected run. No candidate or schedule was selected from that dry attempt.

## Native implementation

The companion worker and end-to-end parity harness are under `native/`. Rust reproduced all 298,664 prospective hard action choices and all 640 policy values from the second study. The source, constructor-independent stdin format, tests, timing and numerical checks are described in `native/README.md`.

The native worker source is versioned in hepta-runtime PR #152. Fetch it using the compiler instructions in native/README.md before executing the parity check.

## Blinded weight-programming submission

A separate agent received five anonymous checkpoint copies, each with an 85→48→4 tanh architecture and 32 trusted reference logits. Hidden units were independently permuted and sign-reparameterized before injection. The agent received no fault family, healthy tensors, task graph, withheld outcomes or feedback. The entrant was instructed to read only its private working directory. No OS isolation was asserted. It wrote a program that enumerates one- and two-column readout supports, fits a small linear system on 24 probes, verifies on the remaining eight, and recognizes sign and permutation structure. This is one agent submission on five constructed cases.

Four modified networks were repaired with 15 changed scalars, and the clean network was kept. Ten support-disjoint complete task worlds contain 5,179 states. Artificial faults originally changed 185 state decisions. The repaired networks matched all 5,179 healthy decisions and all ten policy payoffs, with at most 2.23e-16 readout deviation. One injected hidden input sign change was canceled by four outgoing weights. This reconstructs its behavior without identifying which physical parameter was originally altered. A favorable original-to-damaged realized value on one world also shows why returning to a trusted baseline and improving a baseline are separate experimental endpoints.

Reproduce with the previous evidence package, the NumPy version above, and the recorded seed:

```bash
mkdir -p blind-replay/design blind-replay/entrant
OPENBLAS_NUM_THREADS=1 python blind/make_cases.py "$HEPTA_WSP_INPUTS/neuron" blind-replay/design/support "$(python -c "import json;print(json.load(open('blind/protocol.json'))['seed'])")"
cp blind-replay/design/support/*.npz blind-replay/entrant/
cp blind/solver.py blind-replay/entrant/
OPENBLAS_NUM_THREADS=1 python blind-replay/entrant/solver.py blind-replay/entrant
OPENBLAS_NUM_THREADS=1 python blind/evaluate.py blind-replay/design "$HEPTA_WSP_INPUTS/neuron" blind-replay/entrant blind-replay/scored.json
```
