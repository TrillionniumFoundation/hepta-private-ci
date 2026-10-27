# Observed difference between two recorded training repetitions

This observation compares the existing round-two cumulative LoRA training in
[run 40498180354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40498180354)
and [run 40501186161](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40501186161).
Both training receipts report successful completion. The first campaign failed
later at evaluation; its additional ten gradient steps remain a failed-attempt
cost and are not part of the successful campaign's cumulative budget ledger.
No training was rerun to make this comparison.

The actual parent readback, parent payload hash, request, token schedule, seed 7,
four CPU threads, learning rate 0.001, ten steps, 526 input tokens and 40
supervised tokens agree. The recorded training-child and helper source hashes
also agree. The whole Hepta source differs: the successful run changed the
campaign's isolated evaluation entry. The JSON identifies both exact sources
and the relevant original record hashes.

The receipts report different adapter roots:

| Run | Reported adapter root |
| --- | --- |
| 40498180354 | `35da228e379dcf1f5f830fc3ad7f4c9993b80700b4032f921cf8db2e91656487` |
| 40501186161 | `d2db4d2626a4fcc7057c450adf4d94987c83b7956933ead4b08c3f4be7ed784d` |

Reported losses differ too; the maximum absolute difference across the ten
reported decimal values is `0.00001323223`, at step nine. This is a comparison
of recorded results. The separate checkpoint archives were not downloaded
locally, so this observation does not independently compare their tensor bytes.

The recorded wheel pins, distributions, preflight mapped native files, Python
3.12.3, Torch 2.9.1+cpu and platform fields agree. The two runtime inventories
contain the same 27,198 paths; 530 file hashes differ, all for `.pyc` files.
All recorded non-`.pyc` hashes agree. The cause of those bytecode differences
was not established. The host records differ in mount information; neither
records CPU model or microcode, nor establishes an immutable held runtime
closure or a known effective memory limit.

These two runs therefore do not establish bitwise reproducible training from
the recorded pins alone. They do not establish a hardware cause, identical
complete execution environments, or impossibility of neural consensus. A
consensus contract still needs explicit numeric and verification semantics.
No quality threshold, original receipt, CURRENT or qualification was changed.

The complete original records are retained by the
[failed-run increment](../controls-ci-001-60df5f93/README.md) and the
[successful-run increment](../controls-ci-002-6ba1a5b3/README.md), using the
[documented byte-exact restoration procedure](../INCREMENTAL_RECORDS.md).
[comparison.json](comparison.json) records the inputs, losses and limitations.
