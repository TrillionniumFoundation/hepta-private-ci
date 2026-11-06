# External C4 synthetic census coordinator — prepared, not executed

`run_c4_synthetic_census.py` prepares the existing two synthetic children of
the fifteen-arm `pon_work_expensive_v1` example. It is external to the frozen
C4 tree. It does not execute the full campaign, Mode-A, model generation,
learning or Rust tests. Desktop/Cargo/native execution has not occurred.

## Fixed scope and review result

The source anchor is Chain C4
`8df4b21d893906570d48f5beafabb3b31e0aefbc`, tree
`6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`. Native arguments after argv[0]
are exactly the two original recorded synthetic invocations: attempts 64,
samples 8, reuse 16, target 0 then 1 and the predeclared historical derived
seed. Both have empty stdin, no material argument and the original 300-second
deadline, 256 MiB stdout cap and 1 MiB stderr cap. The frozen original
`bounded_process.run_bounded` supplies process-group cleanup unchanged.

`validate_prelaunch.py` parsed the coordinator AST and performed 23 local
argument/source-pin/binding checks. Its invented dictionaries only exercise
the new caller-parameter binding; they are not native streams and are not
passed to the original reader. Neither the coordinator's main function nor
Cargo, native processes or the proc collector ran in these checks. The
receipt records the exact coordinator SHA and carries no qualification.

## Actual executable binding

The unchanged original `verify_ci_source.py` checks the complete tracked
worktree before and after, including hidden index flags and raw Git blobs.
The coordinator also checks the exact commit/tree, Cargo.lock, Cargo
configuration inputs and default release environment. Bootstrap helper
bytes are pinned before use. Toolchain probes require actual Rust 1.95.0 on
Linux x64. The documented offline locked build keeps the original package,
two examples, default release profile and two jobs. Its only added argument
is `--message-format=json-render-diagnostics`, so Cargo's exact example
source, executable path and profile are retained. The package's empty
default feature definition is represented by Cargo as the named
`["default"]` feature; optional OpenSSL is not enabled.

The build artifact is archived in the new receipt directory. A byte-identical
copy named `pon_work_expensive_v1-<ELF-SHA256>` is placed beside the original
build artifact in `release/examples` and becomes the actual argv[0]. The
directory is unchanged, preserving possible loader `$ORIGIN` lookup. The
exact example reads only `args().skip(1)` and has no `current_exe` asset
lookup; its synthetic branch calls `materials(None, None)`.

This filename allows the already reviewed `test_elf_capture.py` to be used
**without changing its implementation or name-matching rule**. The frozen
helper SHA256 is
`64489779d88a399040e20f939fe878f8d20fa86a60b435a2d7896186dc64d87a`.
Each native child has a separate capture interval bound to this coordinator's
actual PID/start ticks. The coordinator requires one actual `/proc` ELF
capture per child, matching source identity, ancestry, post-open PID/argv/path/
inode checks and the build/launch/retained ELF hash. A copy/hash before
execution cannot substitute for a missing actual capture. Missing or
mismatched capture leaves the component failed.

The helper's legacy `observed_selected_tests` field contains the actual
`--work-expensive-v1` CLI selector in this use. It is not a Rust test count.
The helper's earlier utility controls do not qualify this newly assembled
coordinator or C4 native execution. Polling and ELF copying occur during the
native process; observer CPU/I/O can affect wall measurements and are
explicitly recorded. The coordinator process CPU, child command rusage,
native ThreadCPUTime and native Instant wall durations remain separate.

## Readback and failure behavior

Each child is processed by the original standalone reader with two
calibration samples, six evaluation samples and the original 1/5/20 ms
postprocessed CPU budgets. The additional caller binding requires native v2,
the exact fifteen arms and nine classes, source request seed/target/counts,
the actual returned raw SHA/size, all 1,080 requested cells and no failed
cells. Dense and Sparse each must have 72 complete cells, 64 actual attempts
and four actual setup epochs per cell. Unsupported specialized constructors
remain explicit paid observations. The two reports must have equal material
and per-cell mathematical stream identities across their targets.

Failed native/reader output is kept. Both declared children are attempted
once when source/image prerequisites and the external time window permit;
there is no retry or sample reduction. A native child is not launched unless
the full original 300-second allowance plus collector finish time remains.
Final PASS also requires both complete bindings, actual executable captures,
cross-target consistency and unchanged complete source/configuration. A
timeout, missing raw, source drift, compiler mismatch, reader failure or
capture failure cannot become PASS. These are finite component receipts,
not public service or work-hardness qualification.

## Separately preregistered external limits

These limits are new to this coordinator. In particular, its 900-second
build cap is not borrowed as an original work-expensive-owner budget, and
there is no imported five-second termination grace.

| Operation | New external cap |
| --- | ---: |
| Entire coordinator, including final guards | 3,600 s |
| Project preflight | 120 s |
| Each complete source guard | 600 s |
| Each identity probe | 30 s |
| Offline locked metadata | 120 s |
| Offline locked release build | 900 s |
| Each original reader process | 180 s |
| Each frozen collector finish | 60 s |

The two native deadlines remain the original 300 s each. Native limits are
never shortened to fit a remaining outer window; insufficient time is a
recorded failure before launch. Other external commands may use less than
their cap when the overall window is nearly exhausted. Final elapsed time
above the outer limit fails. Filesystem and process cleanup are not hard
real-time guarantees.

## Prospective handoff command

Only after root review and the H1 window, place the reviewed coordinator and
unchanged frozen collector outside C4, verify their hashes, then invoke the
following under W1's exclusive execution window. This is a prepared command,
not a statement that these two uploaded files or the new receipt directory
already exist remotely.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4/tools/run_c4_synthetic_census.py \
  --root /home/qian-qi/work/chain-joint-20261105-93bfc-current \
  --target /home/qian-qi/work/chain-joint-20261105-93bfc-w1-target-C4 \
  --out /home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4/synthetic-census-two-child \
  --capture-helper /home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4/tools/test_elf_capture.py
```

The output directory must be new. The existing C4 source is not switched,
edited or repaired by this script. Missing prerequisites stop with evidence;
the script does not fetch dependencies or alter configuration to force a pass.
