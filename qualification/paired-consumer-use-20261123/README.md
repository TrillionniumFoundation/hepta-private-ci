# Subsequent use of an enrolled candidate by B

This research profile accepts a released paired admission from the source-training intake. The installed native Linux verifier must support the two consumer statements. Record its digest at original intake installation. A historical journal with an older pinned binary retains its original identity.

Run the following commands under the protected study owner with `PYTHONPATH=scripts`. In the examples, `C` denotes `python -m cell_experiments.paired_consumer HOME ADMISSION MATERIALS`. The owner keeps the journal, model files, private task, answers and business evidence local.

| Command following C | Result |
| --- | --- |
| `select` | Run the released pair in the ordinary paired cold evaluator, retain both raw arms and select the candidate only if it improves the future panel and preserves every passing old item. |
| `request-scope TASK` | Emit JSON for the pinned native CLI's `--print-statement`. B submits those exact bytes through the original protected UI. |
| `run TASK REQUEST_DELIVERY ROOT_PID SQLITE_HOME ROUTE_JSON` | Verify B against the original enrolled principal before opening the private task. Generate once in a fresh local process with the selected candidate and save the raw bytes. |
| `outcome-scope TASK EFFECT accepted` or `rejected` | Emit the corresponding scope after B receives the original answer and chooses a decision. B submits the printed native statement through the original UI. |
| `report TASK EFFECT DECISION OUTCOME_DELIVERY ROOT_PID SQLITE_HOME ROUTE_JSON` | Verify the distinct outcome event, recover the original evidence and retain the first decision. |
| `verify-request TASK ROOT_PID SQLITE_HOME ROUTE_JSON` and `verify TASK ROOT_PID SQLITE_HOME ROUTE_JSON` | Independently recheck both source deliveries with fresh protected handles and their respective routes. Reopen the local output and original business material. |

`TASK` is the study's canonical JSON SHA-256 of a model-visible task with `input` and optional `messages`. The original site puts its JSON into the registered inbox at `consumer-task-TASK.json`. The operation includes the admission and observed selection digest, so it changes if either changes. Requests reusing a covered prompt or token sequence are refused. The protected launcher supplies the existing Root socket on descriptor 3 and the held pidfd on descriptor 4 to commands that verify delivery. The inference subprocess receives neither.

The run command returns the operation and run/output digests. The site delivers the exact bytes in `HOME/ADMISSION/consumer/OPERATION/answer.utf8` to B. `EFFECT` is SHA-256 over the original business evidence bytes at `consumer-effect-EFFECT.bin` in the registered owner inbox. The outcome scope binds the run receipt (including its unpredictable nonce), answer bytes, effect and decision. A restart after a completed generation returns the original. An interrupted generation with an uncertain result remains spent to retain the one-use authorization.

The evidence establishes a local execution observed by the study owner and B's reported decision when the original live enrollment and grants are present. Business success, use of weights on another device and payer authorization each require separate evidence. Engineering fixture records are labeled and count zero human participants.

The focused qualification builds and saves a tiny GPT-2 parent and takes one actual SGD step to produce the child. It runs two later tasks and retains the artifacts for each, using explicitly simulated native delivery and participant identities. The archive includes the model files, frozen pair, both cold arms, selected-model token IDs, raw UTF-8 answers, source fixtures, native fixture inputs, nonce, local receipts and subsequent reports. To reproduce from the pinned Cell integrity CPU environment, run `PYTHONPATH=scripts python qualification/paired-consumer-use-20261123/qualify.py NEW_DIRECTORY`.

## Retained engineering run

The hosted export at code revision `0cf29b6a13343dc8e3e162414b405cbb2e90e88b` produced two subsequent generations. Both emitted the UTF-8 byte `1` from the selected saved model. The same fictional B identity reported one acceptance and one rejection on two distinct tasks. The parent failed the prospective fixture, the child passed it, and both passed the original retention task. [Hosted job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45185490646/job/137729876559)

The 48,076-byte inner archive has SHA-256 `db8549ee2f08810072571f2aa3892ff518277fa371f1029566d78a11b7e89360`. The 67 files include the private-format journal and site originals populated exclusively with fictional identities and authored tasks. The standard-library readback rehashed 14 model inventory entries and both decisions. It rejected replaced candidate weights, changed answer bytes, a changed nonce and changed business evidence. From this directory run `python verify_fixture.py CONSUMER_ENGINEERING_ORIGINALS.zip`. [Raw archive](CONSUMER_ENGINEERING_ORIGINALS.zip) · [Independent readback](FIXTURE_AUDIT.json) · [Substitution controls](FIXTURE_CONTROLS.json)
