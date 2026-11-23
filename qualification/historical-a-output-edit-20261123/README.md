# Can a fast output-layer edit recover the historical task?

On public OpenHands case 52, two solvers changed exactly the same 8,288 output-layer coordinates of the frozen Hepta parent. Across six alternating single-thread CPU runs, the direct ridge solve took a median of 0.401 ms and 240 gradient updates took 122.365 ms. On cold autoregressive generation, both models produced the single character `0` on the known coding task and on the retained old prompt. Only the second response passed. The independently frozen full-model AdamW candidate from #7022 produced the requested script on this training example.

| Fixed comparison | Direct ridge solve | Autograd gradient descent |
| --- | ---: | ---: |
| Shared target positions, including EOS | 62 | 62 |
| Objective, evaluated after reloading float32 weights | 2.19215249 | 2.23676417 |
| Median time to fit the head | 0.401 ms | 122.365 ms |
| Time range across the six fits | 0.318–3.790 ms | 101.023–192.483 ms |
| Cold model load for the scored run | 130 ms | 161 ms |
| Known historical task | Fail | Fail |
| Frozen old task | Pass | Pass |

The training inputs comprised the historically successful 59-byte script and a researcher-authored rehearsal example. Each sequence contributed half the objective. Both methods used the same frozen features, weighted one-hot logit target, ridge penalty and starting output weights. GPT-2 originally ties the output projection to the input embeddings. Both comparison models use an independent copy of the projection so the inputs stay fixed. Reload checks found all 28 tensors from the parent unchanged in each arm and reproduced both objective values from the newly saved projection.

The shared model load took 114.1 ms and feature extraction took 16.3 ms. Fit timings exclude shared setup, file I/O, process launch and cold serving. The six times per solver measure timing variation on one host and one task. The broader full-model update in #7022 uses a different parameter set and loss. These results establish a local solver speed comparison and a failure to learn the task through these two edits. Equal-quality training speed, other editing methods and transfer to a subsequent user require separate measurements.

## Reproduction

Use the case directory and pinned public Parquet release referenced in #7022. The run used one CPU thread, offline Transformers, PyTorch 2.9.1 CPU and a network-isolated Linux namespace. Install the same numerical dependencies as #7022. Supply an unused output directory to the first command.

```sh
export PYTHONPATH="$PWD/scripts" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
case_dir=qualification/public-historical-a-qwen2-052-20261123
study_dir=qualification/historical-a-output-edit-20261123
python "$study_dir/compare_heads.py" "$case_dir" "$parquet" "$new_output"
python "$study_dir/check_saved.py" "$case_dir" "$parquet" "$new_output"
```

`PLAN.json` was fixed before fitting. Its SHA-256 is `4e0b3344b1f0fdcaec154b114b95e57c49b9e283dbf183a517d0866765fb07e4` and its Git blob is `04c2fda087b00725d1f7705279dc174ba40f9c68`. `material.zip` includes both complete models, tokenizers, manifests, timings and original cold predictions. Extract it to obtain the original `run` directory for `check_saved.py`. Its SHA-256 is `49bbe9778c6e18172c6b38045727cc9a0efbdbe9a3b302a98a07a55a6776c918`. The registered future-user candidate is documented in #7022.

[Historical task, source attribution and frozen full-model candidate](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7022)
