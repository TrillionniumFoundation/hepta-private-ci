# Restore and replay the measured phase

Use numerical source commit `3257b035e5dc3c381e1a2342ba69d55a0a35293b` and
reporting source `92bc5d9913eb60316a9620e677e47e21ee96d19d`. The final branch may
contain required mechanical formatting; the original measured versions remain
available. No remote CI result is required.

## Prerequisites

The measured private-Head runtime was CPython3.12.14 / NumPy2.2.6 on Linux x86_64,
with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` and bytecode writes
disabled. Native Rust used 1.95.0 and the unchanged workspace Cargo.lock. The
recorded ELF is platform-specific; its exact SHA is bound in `native-freeze.json`.
Rebuilding on a different platform is a new qualification run.

The source pilot uses its separate CPython3.8.20 runtime and
`pandas-pilot/resolved-requirements.txt`. The interpreter differs from the upstream
3.8.3 declaration. Installed environments and shared model checkpoints are not
in the archive. The measured source-built pandas extensions are retained, with
compiler/ABI/runtime/input receipts; they are not general portable wheels.

## Verify and restore all recorded bytes

Run the existing `qa/stem-bakeoff/package_cell_local_evidence.py` tool:

```bash
python qa/stem-bakeoff/package_cell_local_evidence.py restore \
  --archive hepta-cell-native-resume-pandas-evidence-v1.tar.gz \
  --index hepta-cell-native-resume-pandas-evidence-v1.tar.gz.index.json \
  --output /tmp/hepta-cell-next-restored-new
```

Expected archive SHA256:
`3ac97d19ac129517e49df6ff880de6df6126193fe92a81b80f14a76690a1413e`.
Expected index SHA256:
`6ce025c85a10060fc57b9c103773adcb323f37025847b6f575d4cdf2689dbb8a`.
The verifier checks all 608 files and 507 content objects and recreates ordinary
independent files. Recorded absolute paths remain historical provenance.

The format records files, not empty directories. Create the empty
`RESTORED/pandas-source.git/refs` directory before using that bare Git repository.
This does not rewrite any restored bytes. Both exact commits and their trees
must match `pandas-pilot/source-acquisition.json`; `git show COMMIT:PATH` reads
original source directly from the restored objects. Hooks and original worktree
pointers are deliberately absent.

## Native replay without the original workspace inputs

Use `native_learned_probe.py` with:

- `--export RESTORED/native-export`;
- `--manifest-sha256 f9ce2af5bc4e4634463bd9b7275690b36742c005fb6a86714ca4e4cf4a9ee13c`;
- `--binary RESTORED/native-runtime/learned_cell_replay.elf`;
- `--binary-sha256 a4efd3bac9676ce09bd93955ade0955daf87f2057a51566ebe856ab09394b89a`;
- a new `--output` directory.

After checking the binary SHA, explicitly enable its execute bit; restore itself
does not execute or make any artifact executable. The probe passes only the
request and its independent SHA to Rust. It compares all original 27 × 64 × 2
logits and all argmax values against the separately retained NumPy reference.
This adds 1,728 native Head-row evaluations and zero optimization or Encoder calls.

## Verify all three complete optimizer states without training again

For each mode `linear`, `gated`, `residual`, run
`cell_optimizer_resume_worker.py` in a new process with `--kind verify`,
`--target-cursor 60`, the restored `resume-attempt-1/plan.json`, its external SHA,
the restored `workers/MODE-segment-60/checkpoint`, and a fresh output directory.
The verify branch does not load the original bundle, initialize a new model,
advance the optimizer or publish another checkpoint.

| Binding | SHA256 |
|---|---|
| Run plan | `39bc697ae00b8903a91a4946ee8aecbf4d3eabc400d4dc1abb779b6036bf1fed` |
| Linear checkpoint manifest | `d3af03c961f12cc020f368835bdc25f70d1341bfea415f9dfcc07ca8904ddef9` |
| Gated checkpoint manifest | `698bd944b03968e05c825c49484a440b2665ab1384a27ee3e80c5960d1f6ebe3` |
| Residual checkpoint manifest | `94b27e4f269ce594f5a5010ba37a92475c3eb1081830e5af55d9f17f50c0ef1d` |

Compare every state-array SHA, input/plan identity, 17 final step counts and the
trajectory to the externally retained reports. Each fresh verify must report
zero optimizer and example updates. A new full 24-worker experiment is optional
and costs another 3,060 private updates; it was not used for archive verification.

## Preserve scientific and accounting boundaries

The pandas primary remains null because the frozen whole-action rule rejects
skip/xfail observations. Retaining sem/std failure-to-pass logs does not authorize
relabeling it or presenting a second selected run as fresh evidence. There are
three valid negatives and no valid positives in this one-group TRAIN pilot.

The first cost ledger is a pre-packaging snapshot. Closing receipts add archive
creation/restoration, the second native execution, three zero-update verifies,
and final lint/format operations without recounting nested timings. Wall sums
are measured work intervals, not end-to-end session time. Unknown work stays
unknown. All local tests and numerical replay finished before the final
repository `just fix -p codex-hepta-neuron` and `just fmt --base` operations.
