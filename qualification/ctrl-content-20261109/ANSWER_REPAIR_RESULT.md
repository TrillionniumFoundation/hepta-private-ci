# Actual native answer fit: no quality improvement

The prospectively pinned fit completed on ai395 under original durable job
`1a1c465c128-cf39-2e0`, operation key
`ctrl-answer-repair-fit40-20261110-e323-v1`. Original status is succeeded/exit0;
3,483 stdout bytes and zero stderr bytes are durable, complete and untruncated.
The exact request SHA is
`3ea9d00f6dc1be41427272a1f79169d3b2bd4b56d8b1b97ec7693be9c9b4824e`.

The run verified all 60 original source pins, read 200 original fitting rows and
deduplicated them to 160 states over 40 sources. Four declared 1,000-step trials
trained on 32 sources and tuned on 8; selected trial 2 used learning rate 0.1 and
L2=0 before the 40-source refit. All four inner-tuning quality scores were 0.625.
Only `answer.weight` changed. All other tensors remained bitwise equal, the
candidate cold-loaded identically, and NumPy/Torch export selection differences
were zero. CPU Torch was 2.9.1+cpu.

| Fitting diagnostic                |  Frozen base |    Candidate |
| --------------------------------- | -----------: | -----------: |
| Source-balanced selection quality |       0.5375 |       0.5375 |
| Covered-state source-balanced NLL | 0.1156530364 | 0.0218154284 |

74 of 160 states lack a correct candidate. Consequently 86/160=0.5375 is the
quality ceiling for these fixed fitting candidate sets; the baseline already
attained it. A separate read-only check verified exactly four unique raw feature
states in each of the 40 sources, and 160 raw states equal the 160 native encoded
states. Thus the source-balanced capacity agrees with this ratio; see
ANSWER_REPAIR_CAPACITY.json. Lower NLL here changes confidence and does not demonstrate an
accuracy gain. No independent future label was read. The remaining 37 sources
must stay sealed until a complete prospective study is frozen.

Worker time was 4.045889 seconds, CPU 3.986101 seconds and peak RSS 269,992 KiB.
The outer worker took 4.274599 seconds including private source staging and child
execution. These durations exclude HeptaRuntime transport; provider charges and
energy remain unknown. They do not establish complete-cost benefit.

The actual result, outer receipt, source-freeze receipt, original stdout and
independent readback are retained alongside this report. Parent independently
read the three native artifacts and verified their exact SHA/byte bindings.
Filesystem access and byte checks do not establish separate native-owner or
independent-evaluator key attestation.

Disposition remains **NoUpdate / HOLD**. This closes the missing real tiny-fit
execution and export evidence, while content generalization, independent policy
returns, full costs and production adoption remain unproved. Changing answer
weights also changes attention-weighted public state/confidence; unchanged
encoder parameters do not imply unchanged controller inputs or calibration.
