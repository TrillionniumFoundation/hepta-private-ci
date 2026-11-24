# Signed-only supplemental control

This is a descriptive supplement registered after the main 72 results were available. It reuses the main train/development/test families, including the now-public test family; it is not a fresh holdout or part of the original preregistered 72-case qualification. The main artifacts and selection remain unchanged.

Only the persistent recurrent topology changes: original `message_mode='flow'` removes boundary messages, and `synaptic_mask[:, N:2*N] = 0` removes unsigned event-rate messages. Thus the only signal transmitted between populations is signed event flow. Local probability, value, risk, and readout state remain present. Sender populations receive the same raw input; receiver populations have no direct raw-input route.

The original 14 source files, data, seed initialization, per-width backend, 180 training-CPU-second / 512-update cap, optimizer, and development-only checkpoint selection are retained. A separately bound factory substitution is applied only inside each fresh training worker. Saved masks permit the original core model to reload the control without any factory patch at test time. All nine terminal records and checkpoint masks are checked and sealed before any supplemental test data are constructed.

`run.py` is a Linux operator-specific experiment driver: its `resource` accounting and `ru_maxrss * 1024` conversion target the existing Linux CPU host. The neural model core is unchanged. Each worker uses one Torch thread; nine workers may execute concurrently. Report worker/parent/stage costs separately, retain errors, and do not convert CPU time to energy.

`summarize.py` is read-only postprocessing. Numerical learning thresholds are reused descriptively; three seeds and the same synthetic source family do not establish out-of-distribution or foundation-model superiority. Comparisons to main `qvi_flow` distinguish signed-only transmission from the main unsigned-plus-signed flow condition.

## Reproduction

Use a fresh run directory containing the `qualification/` source tree and `postprocess/verify_predictions.py`. Copy `MAIN_PROTOCOL.json` from the sealed main run's `PROTOCOL_FROZEN.json`, and `MAIN_FINAL_RESULTS.json` from that same main run's `training/FINAL_RESULTS.json`. These are identified inputs, not a newly selected baseline. The fourteen base dependencies and the Python/NumPy/Torch runtime must match the main manifest exactly; preparation fails otherwise. The independent verifier is the unchanged main helper with SHA256 `55a6279d728f08872c091434b57a9a2943fd90cbdcb81d9d1966cfd0e1711f34`.

Run the following from that fresh directory using the declared CPU runtime. Existing protocols, attempts, claims, and summaries are create-only; the retained evidence directory is not a rerun target.

```bash
HCSN_PYTHON=/home/qian-qi/hcsn-e901-torch280-cpu-runtime-20261112/bin/python
"$HCSN_PYTHON" -m unittest qualification.hcsn_signed_control_20261124.tests -v
"$HCSN_PYTHON" -m qualification.hcsn_signed_control_20261124.run prepare --manifest "$PWD/PROTOCOL_SIGNED.json"
"$HCSN_PYTHON" -m qualification.hcsn_signed_control_20261124.run launch --manifest "$PWD/PROTOCOL_SIGNED.json" --training "$PWD/training"
"$HCSN_PYTHON" postprocess/verify_predictions.py --training "$PWD/training" --output "$PWD/INDEPENDENT_METRICS_VERIFICATION.json"
"$HCSN_PYTHON" qualification/hcsn_signed_control_20261124/summarize.py --root "$PWD"
```

The driver launches nine fresh single-thread workers and waits for the entire training roster before opening any test worker. Our external operator job imposed a 900% aggregate CPU quota, 8 GiB memory limit, and 900-second job deadline; these cgroup limits are external to the CLI. Per-attempt training remains capped by the unchanged 180 CPU seconds / 512 updates. The `POSTPROCESS_REVISION.json` receipt preserves a read-only analysis robustness revision separately from the four frozen supplemental training files.

Interpret test costs using full worker or stage receipts: the supplemental pair-body timer starts after data/checkpoint/model setup, whereas the original main pair-body timer included checkpoint handling. Those two nested body fields are not interchangeable timing baselines.
