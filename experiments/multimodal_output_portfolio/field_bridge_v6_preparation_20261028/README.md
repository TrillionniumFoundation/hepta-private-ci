# V6 preparation: branch state and literal storage accounting

**NOT_REGISTERED / NOT_EXECUTED.** This directory contains an executable
preparation stage and synthetic checks. It contains no scientific runner,
Torch adapter, fitted head, training, new endpoint or holdout result. Original
V5 scientific **FAIL**, rejection and no-admission status remain unchanged.

## State covered

| Record component | Preserved or checked |
| --- | --- |
| Execution binding | Proposal, frozen source, runtime, prospective protocol and global resource-limit identities |
| Immutable dependencies | Original generator, frozen base and reward observer identities; declared tensor inventory/layout, module modes and named RNG inventory; approved roles; context/input identity |
| Guard | Original immutable guard panel, paired source IDs, output identities and all float64 values |
| Mutable model | Named contiguous CPU arrays, mutable buffers and per-parameter `requires_grad` flags |
| Optimizer | Complete declared SGD groups, ordered integer IDs, a bijective ID/name mapping, and momentum buffers including absent initial state |
| Incoming gradients | Named dtype/shape/bytes, preserving `None` separately from a zero array |
| Randomness | Opaque Torch CPU RNG bytes; Python, NumPy and explicit named-generator states |
| Logical progress | Seed, schedule, prefix/policy identity, clock, remaining microsteps, decision index and guard48 |
| Future inputs | Every remaining paired data/noise mark and the complete schedule identity |
| Actual work | External monotone counters, never restored with the branch checkpoint |

The declared algorithm fixes seeds 17/29/43, schedules 6000–6003, baseline
actions 2/3/3, six guard48 decisions and 288 microsteps. It rejects unknown
record fields or changed execution/context bindings. `seal` and `restore`
require the caller's separately held environment identity; computing that
identity from an untrusted record is not an independent verification.

`codec.py` preserves typed keys, tuple/list distinctions, exact scalar float
bits, array dtype/shape and literal uncompressed bytes. No pickle is used.
Whole-envelope and per-array hashes plus canonical reserialization are checked.
Writes are exclusive, size-limited and fsynced; partial writes are not deleted.
`Layout` permits allocation-free size measurement, but cannot be written as
observed tensor evidence.

`branch_state.py` restores a fresh independent record before each action.
`tests.py` checks every one of the 24 action orders with the same synthetic
transition. Rejection restores the mutable record while the logical clock and
external work advance. Zero action still charges work. Callback failure retains
completed branches, the failed state and work before/after; cost regression is
reported as an additional integrity failure even when the callback also raises.

## Scope of the tests

Run the pure NumPy suite from the repository root:

```sh
python -I -B experiments/multimodal_output_portfolio/field_bridge_v6_preparation_20261028/tests.py
```

The fixture contains two tiny arrays, a toy recurrence and synthetic Torch RNG
bytes. Passing it proves record serialization and synthetic branch isolation;
it does not prove PyTorch capture/restore, scientific branch replay or efficacy.
A later separately reviewed live adapter must capture the actual named tensor
inventory, buffers, module modes, RNG generators, immutable context and runtime
settings, verify unchanged frozen models, and test replay using the pinned
learning kernel. Nothing here reconstructs omitted historical RNG/gradients.

## Storage accounting

`budget.py` uses the actual envelope serializer's measured byte count. A small
sample only bounds a real artifact when its entire permitted shape and metadata
range has been checked. Missing bounds stay unknown. The nine required artifact
classes cover all parent and terminal checkpoints, paired probe outputs,
endpoints, heads and an explicit bulk cap for traces/features/bindings.

The estimate reserves raw files, one interrupted exclusive write plus its
failure receipt, a proposed 510 MiB archive writer cap, a full literal
restore, retained earlier failed archives and an 8 MiB buffer. It assumes a
single scientific writer; parallel workers or another archive attempt require
their extra retained bytes to be counted. Compression savings are never assumed.
The future archive writer must enforce that cap; no archive writer is implemented
here. The cap can itself be hit and fail; it is not a guarantee of packing fit.

Capacity uses `f_bavail * f_frsize` for every UID and sufficient free inodes.
It requires at least **2 GiB** and, when larger, the calculated peak plus
256 MiB reserve. `f_bfree` is reported, never substituted for `f_bavail`.
Research start remains false even if a hypothetical capacity check passes.

`BUDGET_PLAN.json` deliberately leaves real candidate bounds unknown. To rerun
the capacity report, choose a new output path; the tool never overwrites:

```sh
python -I -B experiments/multimodal_output_portfolio/field_bridge_v6_preparation_20261028/budget.py --plan experiments/multimodal_output_portfolio/field_bridge_v6_preparation_20261028/BUDGET_PLAN.json --filesystem . --output /tmp/v6-preparation-budget-new.json
```

`SOURCE_REFERENCES.json` binds the inspected old sources to the explicit V5
scientific registration, independent of the changing engineering branch HEAD.
`PREPARATION_REPORT.json` records the actual synthetic measurement and test run;
`BUDGET_REPORT.json` records the incomplete candidate estimate. Neither is a
new research preregistration, an admission decision or permission to upload raw.
