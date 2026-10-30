# Trained distributional model: actual owner and fresh-process recovery

This separately registered engineering study uses the selected v2 distributional MNIST model. Its own first64 TRAIN traces fit the task-value observation model; six original VAL images form two three-task streams. These are explicitly reused TRAIN/VAL data, not a fresh-test quality cohort.

Both full finite-queue task values and a same-observation myopic value ablation feed real-valued scores to the actual native owner. The latter deliberately omits later tasks from its decision table while the executed queue still has three tasks. The confidence-state map is quantized/piecewise constant; no global differentiability claim is made for this external task controller.

| Price | Policy | Stream | Actual reads | Correct tasks | Actual later correct | Utility |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.001 | tabular_bellman | 0 | 44 | 0 | 0 | -0.044000 |
| 0.001 | tabular_bellman | 1 | 43 | 1 | 0 | 0.957000 |
| 0.001 | tabular_myopic | 0 | 42 | 0 | 0 | -0.042000 |
| 0.001 | tabular_myopic | 1 | 44 | 2 | 1 | 1.956000 |
| 0.005 | tabular_bellman | 0 | 43 | 0 | 0 | -0.215000 |
| 0.005 | tabular_bellman | 1 | 43 | 1 | 0 | 0.785000 |
| 0.005 | tabular_myopic | 0 | 44 | 0 | 0 | -0.220000 |
| 0.005 | tabular_myopic | 1 | 44 | 2 | 1 | 1.780000 |
| 0.02 | tabular_bellman | 0 | 9 | 0 | 0 | -0.180000 |
| 0.02 | tabular_bellman | 1 | 16 | 0 | 0 | -0.320000 |
| 0.02 | tabular_myopic | 0 | 9 | 0 | 0 | -0.180000 |
| 0.02 | tabular_myopic | 1 | 16 | 0 | 0 | -0.320000 |

Active and mid-quiet checkpoints were resumed in different Python processes. All subsequent neural outputs, actual actions, native checkpoints, final neural state and task reward matched the uninterrupted fixed8 engineering fixture. The active snapshot preserves the full distribution and refractory phases; it does not collapse to a pressure mean.

Measured worker CPU, including native descendants: **34.607003 s**. Coordinator self CPU is separately retained. Existing content training is identified and not billed as new training in this engineering run. Runtime and reward rows here do not replace the larger frozen-v1 task-control panel.

See PROTOCOL.json, REGISTRATION.json, TEACHER_LOCK.json, EVALUATION_SUMMARY.json and COMPLETE.json for hashes, assumptions and scope. Every owner journal, explicit STOP rejection, checkpoint and execution receipt is retained.
