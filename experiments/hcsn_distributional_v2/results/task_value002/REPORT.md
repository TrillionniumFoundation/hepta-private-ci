# Regenerative task-value and actual owner study

**Completed scoped experiment.** Exact binary observation Bellman checks and real-data task-control evidence are separate. The MNIST controller uses a train-fitted coarsened Markov approximation; neither its table nor its distilled values are certified as the exact neural belief-state optimum.

## Contract and identities

Each stream has three distinct shuffled MNIST images and 48 model-clock ticks. Every READ consumes one tick and pays the public price. FIRE scores actual classification correctness and terminates that owner/iterator. Two quiet ticks then consume deadline with no observation/model/owner step before a reset next task. These are task-layer actions, not claims that every internal pressure-neuron firing optimizes this reward.

The new 384 source images reproduce and exclude the previous 640 test prefixes, and have zero source-ID overlap with original TRAIN/VAL/TEST or native003. Original validation data and one previously trained backbone are reused. Controllers are selected on actual VAL stream reward, then locked before fresh inference. The task queue is shuffled without replacement; its independent-restart observation model remains an approximation.

The two learned heads have identical five inputs, 66 active parameters, initialization, minibatch sequences, updates, LR searches and checkpoint opportunities. One regresses task Q values (with advantage loss), the other distills ordinary actions from the same teacher. This isolates the training target/objective within a matched MLP, not a novel two-channel architecture. All selected parameters changed and received finite/nonzero gradients.

## Quality, actual execution and complete measured runtime

Scores are means over the three registered prices. The 128-stream counterfactual panel pays for every full-prefix cache computation; its logical skipped reads do not establish compute savings. The separate 16-stream native panel actually stops tensor iteration and resets real owners. Statistical resampling uses one complete three-task stream, averaged over prices.

| Policy | Counterfactual utility, 128 streams | Actual native utility, 16 streams | Actual native CPU / stream |
| --- | ---: | ---: | ---: |
| bellman_value_head | 0.37229687 | 0.51508333 | 0.290893 s |
| ordinary_action_head | 0.36622917 | 0.49383333 | 0.265434 s |
| tabular_bellman | 0.54640625 | 0.88972917 | 0.188940 s |
| validation_schedule | 0.42966667 | 0.57550000 | 0.235835 s |
| validation_risk | 0.42966667 | 0.57550000 | 0.202361 s |

The ordinary reference selected before fresh testing is **validation_schedule**. Value-head minus this reference on the full counterfactual panel is **-0.05736979**, with nominal descriptive stream-bootstrap interval **[-0.09156510416666663, -0.021041666666666646]**. This is not a new significance or architecture-superiority gate.

Counterfactual/native paid-read and correctness parity mismatches: **0/240**. Detailed records are retained; their two evidence scopes are never pooled.

## Future reward, causality and reset

The exact binary fixture holds the observed prefix, noise law, price, current deadline and native profile fixed. Increasing the remaining task queue from one to three adds a genuine subsequent-task value and changes the actual owner from KEEP to STOP. Its receipts are in preflight/FUTURE_VALUE_CAUSALITY.json. Independent actual-label rollouts verify the later tasks produce their own rewards; the future term is not a constant bonus.

Actual MNIST stream ledgers separately record later-task correctness and later net reward. Complete-price response records in AUDIT.json compare first actions at the same observed prefix; these are causal execution checks, not new quality comparisons.

Fresh Python processes restore both a nonempty active neural state and a mid-refractory driver checkpoint. The saved state includes current task, queue identity, remaining deadline, remaining quiet ticks, accumulated ledger and generic nested neural tensors. The complete semantic trajectories, native checkpoints, final neural state and actual utility equal the uninterrupted engineering fixture. This fixture uses a declared fixed8 schedule and is separate from selected-policy quality.

## Cost scopes

New complete campaign CPU: **97.562924 s**, including the coordinator startup/imports, data preparation, preflight, both learned-head searches, teacher fitting/solving, counterfactual and actual native evaluation, and complete recovery verification. Its **94.855243 s** of measured phase processes and all waited native descendants are already included and must not be added again. Preserved earlier failed-attempt campaign CPU is **5.395364 s**, also charged in the scenarios. Historical fixed-backbone search cost **46.474767 s** is disclosed separately; it was not retrained here. The outer supervisor/final audit/report self CPU is recorded separately in ANALYSIS_PARENT_EXECUTION.json.

The value head exceeds the validation-chosen ordinary reference in **0/24** registered cost scenarios. Those are sensitivity calculations with explicit utility-per-CPU rates and future stream lifetimes, not measured money or energy. COST_SCENARIOS.json retains both measured-component allocation and a deliberately favorable ordinary-setup cost lower bound.

## Limits and next use

The noisy-binary oracle is exact for its discrete observation law. MNIST confidence bins discard information and do not become sufficient statistics by running Bellman recursion; predicted future value calibration and task quality must be judged against actual later rewards. The fixed backbone remains the previous v1 network. Any separately attached v2 distributional-model owner smoke/recovery result must keep its own identity and cannot inherit this controller quality result.

Reproduction: invoke task_value_run with a new output directory and the verified raw MNIST source root. PROTOCOL.json, REGISTRATION.json, SELECTION_LOCK.json, all candidate updates/checkpoints, traces, actual native journals, phase receipts, counterfactual arrays, recovery artifacts and this audit are retained. No failed or prior evidence was overwritten.
