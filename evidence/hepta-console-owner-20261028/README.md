# Keep the command owner responsive when its console is not read

The previous executor forwarded every retained child-output chunk to its own
stdout with a blocking, flushed `print`. An unread console pipe could therefore
hold the command owner inside that write, preventing its next deadline check.
The final JSON `print` had a second instance of the same problem when the
record contained a long command. The raw log and atomic JSON output already
provide the persistent result channels.

This change removes those two unbounded console writes. It retains the actual
raw output, original output cap, exact output hash, test-outcome parser, source
checks, command deadline, process-group cleanup and sole-parent reaping. The
workflow executes all command-owner controls before the existing native build
and adds 65-minute outer guards to the two existing 3,600-second commands.
Their inner budgets and the five required Rust packages are unchanged.

## Actual reproduction and verification

The original runner SHA-256 was
`e5e18bbfd9e2a855cb6911dcd40183770a13cd9414bf988f3a50cae9509652cc`.
A controlled, owned Python child with a 0.25-second deadline remained blocked
after 1.501 seconds while the console was unread. Draining the console allowed
that same owner to enforce its deadline, kill its own process group and reap
its direct child. The retained 131,072 output bytes and actual timeout record
are included here. This demonstrates a real defect; it does not establish the
cause of either ongoing hosted Rust run.

Three actual CLI regressions fail on the original runner. They exercise an
unread console during a real deadline, successful complete 262,144-byte output,
and a final JSON receipt containing a 90,000-character command. The tests delay
draining until after the observation. On the original failure path, draining
allows the executor itself to perform its normal cleanup.

After the fix, all **77 tests pass, with zero failures and zero skips**, in
28.277 seconds. The five original test files, containing the original 74
methods, are byte-for-byte unchanged. Two earlier full-suite attempts each
passed 75 tests and errored on two tests because the thin local checkout lacked
an unchanged source fixture. Their logs are retained. Hydrating the exact
original dependency helper and consolidated-source workflow resolved those
fixture errors; the runner was not changed between those attempts.

The required `just fmt` completed successfully with the already installed
Ruff 0.15.13 matching the frozen lockfile. Its environment was reused without
dependency synchronization. Both changed Python ASTs and bytes were unchanged
by formatting, so the completed 77-test run still binds the final Python source.
`source-review.json` records hashes and the independently checked caller audit.
The existing callers consume the output file or return code; none found in the
repository consumes the removed stdout JSON stream.

## Preserve the concurrent upstream changes

The candidate is based on upstream commit
`746d7590990eec46d20400293feb80f499813bd9`, tree
`ee2776d9c032ecb6e44e8f1a480af299dea7b3b9`.
All 18 concurrent upstream changed paths are retained. The workflow was merged
against the exact upstream bytes, and reversing only the narrowly listed
workflow additions reconstructs those bytes exactly.

The metadata-only artifact exporter, all model-payload export restrictions,
ordinary installation and quality gates, resource floor, original model
execution commands, and original model time budgets remain in force. This
evidence contains controlled test text and source metadata. It does not export
checkpoints, trained weights, adapters or hidden payload archives.

## Qualification boundary

This is a command-owner fix with local Python regression evidence. The local
checkout is thin and is not declared a complete source qualification. A fresh
hosted checkout must build and run the actual scoped Rust and neural gates.
Passing these command-owner controls alone does not establish a beneficial
trained child, cross-node ordinary installation, next-task child-byte readback,
or completion of the Hepta neural task.

The change does not promise hard real-time scheduling or bounded filesystem I/O.
The two old hosted jobs are retained as observed runs. Their process groups were
not signalled by this work, and no cause or outcome is invented for them.

Raw regression logs are gzip-compressed without modifying their contents.
The publication manifest outside this evidence directory binds every committed
file by length, SHA-256 and Git blob identity.
