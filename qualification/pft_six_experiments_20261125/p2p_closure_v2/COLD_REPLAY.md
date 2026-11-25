# Fresh-process forward replay of the saved real models

All twelve saved SmallHCSN readout candidates were loaded in separate new Python processes on the configured physical host `pocket4`. Each process replayed both of its already opened test partitions, for 24 partitions and 3,072 examples in total. Every replayed prediction was exactly equal to the corresponding saved prediction; the maximum absolute difference was 0.0.

This closes the distinction between loading matching parameter tensors and executing the restored model's actual forward computation. It is a fresh-process model replay on one physical host. It does not represent an OS cache flush, a new physical host, native daemon adoption, or adoption by another real user.

## Immutable inputs and source

The replay source is `../actual_p2p_v2/cold_replay.py`, SHA256 `7640a060361fbdfde6b65d0836e81531c47e9a80da5e2b3e11a032cba2e7d764`, frozen in Git commit `2a03928bf93bc10d3db2a9afec9915a1eff9c35d` before execution. The model and evaluation inputs were not modified:

| Input | SHA256 or commit |
| --- | --- |
| Candidate publication | `e725f22b5c9806fb1ebb33845085195926a993b4` |
| Candidate seal | `778d7c2d97c056341eca91ba771a79fab9069d26f3ee9f33fb47fbcbdd83a3a4` |
| Frozen study protocol | `5d5e6193ff962ded6e912238f0f87ea969d362bbd7345cf0885f9625c81c89c1` |
| Completed evaluation result | `7d2cea214251752b133f3d3b4fe3e6c593a4605be6f9b65afd417676b6b3f89c` |
| Original test-opening receipt | `6980567387827693e9bf95f607fa0088531b6729650ed1b78edb7eec7812e8c1` |

Before forward execution, each child verified the candidate publication, the exact saved model file hash, the pinned physical implementation, the serialized feature basis, and the fixed runtime. It loaded the checkpoint with `weights_only=True`, checked the installed readout against the sealed coordinate vector, and compared every non-readout parameter tensor against the original frozen physical parent. Those protected tensors were checked again after the forward passes.

The replay reconstructed the same previously opened test inputs from their declared namespaces and required exact input/label test hashes. It then checked exact equality of saved and replayed model predictions, target arrays, and coordinate-based predictions. The largest difference between actual logit margins and their coordinate realization was 2.2160051571518125e-12, below the existing 1e-7 study tolerance. There was no training, hyperparameter selection, or new test-based candidate choice.

## Actual process and cost evidence

The durable task was `1a21278e3f4-ffbe-3fb0`. It completed with exit code 0, complete durable logs, confirmed terminal publication, and both output streams at EOF. All twelve child PIDs were distinct, each reported the recorded supervisor as its parent, and all children exited with code 0.

The twelve complete child processes used 32.603590999999994 CPU seconds. Supervisor elapsed time was 33.0805228180252 seconds, and the outer launcher elapsed time was 33.15569242404308 seconds. These clocks include fresh interpreter/framework startup and model loading; the per-child receipts also separate import, model creation/loading, and forward work. This replay cost is additional to provider preparation, peer training, and the original evaluation.

The execution service delayed the initial start response and one exact same-key reconciliation response, both reporting MCP request timeouts. The original durable job was subsequently located by its request metadata and read to its complete successful terminal state. No new experiment key, changed model, or replacement scientific run was introduced to resolve that control-plane delay.

## Retained evidence

`evidence/cold_replay_v1/RESULT.json` is the exact remote supervisor result, SHA256 `f00f0de9b43410c4bdbd44e6414ed8f6514ca6e12269c8fcdcef3bd2ac18aab1`. The same directory contains all twelve exact child receipts, their independent remote-read manifest, and the complete durable execution receipt. Every child file SHA256 was checked against both the remote read and the supervisor's recorded hash after local saving.

`COLD_REPLAY_INDEX.json` lists the public evidence paths, byte counts, and SHA256 values. The original saved model checkpoints and prediction archives remain in the separate actual-model evaluation evidence, with their identities checked by the replay receipts.
