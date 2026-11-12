# Task-conditioned parameter-layout reference

**HOLD / NoUpdate.** This is an executed synthetic equivalence control, not a
negative-transfer result, learned router or native Population adoption.

## Exact executed source

Clean commit `6b249933d2d5f2503ad78f10e73ce261817a07f7`, tree
`1ce761595c7f7e3a8b9671d42d78172917364417`, on #6143. Python 3.12.14,
NumPy 2.3.5, one OpenBLAS/OMP thread. All source hashes stayed unchanged.
The final default experiment completed **12 real fits and 288 SGD updates**.

Both trained layouts receive identical task IDs, data, initial weights and
evaluation rows. They call the existing `SemanticComponent` producer and SQLite
owner. The shared bank uses disjoint readout blocks, the same hypothesis class as
separate heads; equality is the intended strong control, not a training advantage.

| Per seed and arm | Frozen | Shared bank | Routed heads |
| --- | ---: | ---: | ---: |
| Total private parameters | 10 | 10 | 10 |
| SGD updates | 0 | 48 | 48 |
| Parameter scalar updates | 0 | 240 | 240 |
| Selected-path forward MAC | 256 | 5,248 | 5,248 |
| Gradient MAC | 0 | 4,608 | 4,608 |

All three seeds have identical trained parameters and predictions between the two
trained layouts. Old-task predictions remain identical after new-task training.
Dense serving is a separate extra-cost control: two actual head calls and 128 MAC
per panel, versus one call and 64 MAC on the selected path. Bank copies, provider,
routing and wall/CPU observations are retained separately. Full physical costs,
resident-byte integrals and energy are unknown; physical compute is not matched.

## Verification and original attempts

The combined local suite passed **106/106**, zero failures/errors/skips, before
`just fmt`; formatting preserved all checked Python ASTs. Local tests were not
rerun after formatting. The default experiment above ran on the clean formatted
commit. Hosted checks must independently qualify the eventual evidence head.

An independent reader verified 14 source files against Git and the source ZIP,
35 original artifact hashes, 12 training receipts and 576 prediction scalars
(maximum difference 0), plus costs, retention and SQLite state: **252 successful
arithmetic/integrity checks**, not new tests or model executions. Reopening owners
here is in the same process; this is not whole-daemon cold recovery.

`ORIGINAL_EVIDENCE.zip` retains `reference-final`, its source ZIP and execution
receipt, the complete independent review script/report, all unit-test logs and
the pre-format tested source. It also retains the earlier `reference-01` and the
real checkpoint-write-failure attempt separately. That failure led to recording
completed training receipts before checkpoint writes. The older script was later
reconstructed by inverse patch and matched its original pre-execution hash; its
README states this explicitly. No result or measured artifact was reconstructed.

`SUMMARY.json` binds the archive; its `ARCHIVE_MEMBERS.json` binds every member.
Reproduce the final experiment with `PYTHONPATH=scripts python3 -m
hepta_cells.differentiation_reference --output /new/attempt-directory` from the
repository root. The reference cannot overwrite an earlier attempt or authorize
adoption. Real negative transfer, independent task benefit, retention and complete
cost-matched structural selection remain required.
