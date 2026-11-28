# Actual hosted PFT regression evidence

This evidence-only stage retains the original downloaded Actions artifacts and
job-log readbacks from the first executed 17- and 20-control gates. It starts no
new test, training job or scientific experiment and changes no implementation.

| Gate | Exact source | Hosted run | Controls | Observed test seconds |
| --- | --- | --- | --- | --- |
| Original synthetic gate | `4686c861e54179690c4a668a356a4b0ce57639d5` | [46095491920](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/46095491920) | 17/17 | 12.973420777 |
| Admission successor | `6e60365410d825778bb16b759af893985db97a6b` | [46098100201](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/46098100201) | 20/20 | 13.575321218 |

Both executions report zero failures, errors and skips. The actual hosted
runtime was Python 3.12.3, NumPy 2.3.5 and SQLite 3.45.1. Post-test formatting,
unchanged-source verification and evidence upload succeeded. These are distinct
from the previously published local Python 3.12.14 rehearsals.

`READBACK.json` binds each unmodified ZIP's bytes and SHA256 to its Actions run,
job, artifact and exact source. Each ZIP retains FROZEN, RESULT, suite logs,
executed source and runtime details. All included source files were independently
checked against their frozen SHA256 entries (12 and 15 files respectively).
`job-readback.tar.gz` retains the original UTF-8 job logs and artifact metadata
returned by the GitHub connector, including its observed artifact digests.

The successor's actual concurrent admission control recorded two receiver PIDs,
one accepted write and one refusal, with final revision 1. Its received offer
performed one complete validation and one eigendecomposition; the packet and
full receipt matched the fixed, previously observed baseline. That historical
two-validation baseline was not rerun. Uncapped writers remain uncapped.

The three earlier zero-job workflow-configuration failures remain failures;
their original archive and correction are retained in the ancestor #7208 stage.
No failure history is overwritten by this readback. The two observed timings are
from separate source revisions and are not a paired speed comparison.

`runtime_closure_complete=false` remains explicit. These synthetic engineering
controls establish neither model quality nor learned circuits, user provenance,
native training, adoption or useful-work rewards. No original cache, DEV/final,
user trace or E1-E6 budget is used by this stage.
