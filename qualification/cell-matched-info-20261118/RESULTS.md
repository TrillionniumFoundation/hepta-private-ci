# Result: no upstream gain; retain the research NoUpdate decision

The prospectively frozen candidate `992f2b3de51902448abf5743f94179bf40e11b6d`
completed both 64-update fits and all 96 planned model calls. Every call has its
original request, raw output and business-verifier receipt. The two trained
objectives match on initialization, complete visible trajectories, all per-step
forward/backward shapes, selected head positions and optimizer settings.

All four arms fail all six upstream tasks, on both attempts. This run does not
establish transferable learning value. `DECISION.json` retains **NoUpdate as a
research selection decision**. It does not claim a native-owner NoUpdate event,
adoption, new C/D qualification, FinalUse or settlement.

## Actual updated-policy behavior

Each task received exactly two calls, including tasks whose first answer already
passed. `Selected` means at least one verified attempt passed; it is not the
final-call outcome. Recovery and regression below are actual second-call behavior
of the cold-loaded updated model, using its own first action and actual verifier
feedback. None of these new rollouts entered training.

| Arm | A first / 6 | A final / 6 | A selected / 6 | Recovered initial failures | Regressed initial successes | B selected / 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen base | 0 | 0 | 0 | 0 / 6 | 0 / 0 | 0 |
| Frozen plus A retrieval | 0 | 0 | 0 | 0 / 6 | 0 / 0 | 0 |
| Full-information final-only SFT | 3 | 2 | 3 | 0 / 3 | 1 / 3 | 0 |
| Full-information all-actions SFT | 3 | 2 | 5 | 2 / 3 | 3 / 3 | 0 |

The all-actions objective recovers two failed A tasks and loses all three of its
initial A successes. Its final count remains 2/6, identical to final-only SFT.
The objectives pass different tasks at the final step: two all-actions-only and
two final-only-only successes, with no shared final success. The selected 5/6
cannot substitute for the unchanged final result or the 0/6 upstream result.
The A references are the six original authorized, authored training tasks;
their retention and recovery are not independent generalization evidence.

Across both panels, frozen and retrieval each receive 24 format rejections and
execute no business test suite. Final-only executes 16 suites, with five passing
calls, eleven business failures and eight format rejections. All-actions executes
17 suites, with five passing calls, twelve business failures and seven format
rejections. Both trained arms produce a real format improvement, while none of
their upstream task attempts passes the business verifier. These totals retain
format failures in the task denominator.

An independent rereading of the retained outputs, recorded in
`MECHANISM_REVIEW.json`, changes no scores and makes no new model calls. On B,
both frozen controls emit fenced answers on all twelve attempts. Final-only SFT
has seven format rejections and five executed suites, all of which fail on the
original source. All-actions SFT has five format rejections and seven executed
suites: one passes the original source but kills no negative controls, so it
correctly fails the unchanged business criterion. Nonretrieval second-call
histories are consistently user → assistant → tool. The previous Circuit
message-order problem was not observed in these histories. Format improvement
has therefore not established semantic generalization in this panel.

## Matched training and measured cost

Each objective consumes 40,247 input tokens, 147,456 padded positions, 7,112
language-model head positions and 96 forward/backward operations over 64 updates.
Both start with parameter hash
`bd8d0e3cde37c3a6694bfc02b6a7b49a826e74f85d44f8ce9773f3d3bf9d02df`.
The intended treatment is the loss mask: final-only supervises 5,390 positions;
all-actions supervises 7,112. Both still traverse the same zero-weight backward
graphs. Their measured training windows are 120.32 and 118.74 seconds, respectively;
their CUDA allocated peaks are both 3,755,675,136 bytes. This does not assert
equal physical energy use.

| Evaluation arm | Model / verifier calls | Input tokens | Output tokens | Output-limit hits | Evaluation wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen base | 24 / 24 | 13,285 | 7,191 | 13 | 440.09 |
| Frozen plus retrieval | 24 / 24 | 31,262 | 2,388 | 0 | 165.65 |
| Final-only SFT | 24 / 24 | 10,732 | 2,301 | 2 | 196.99 |
| All-actions SFT | 24 / 24 | 10,577 | 2,370 | 2 | 200.64 |

Evaluation windows include cold loading, generation, actual verification and
model release. The owner records all eight separate child-stage windows, including
freeze, both trainings and the training audit: 1,284.74 wall seconds and 1,304.47
completed-child CPU seconds. These outer stage totals must not be added to their
nested training/evaluation windows. All failed attempts and output-limit hits
remain charged. There are also twelve freeze reference checks and twelve training
reference checks, so the candidate performs 120 verifier calls in total.
Owner checkpoint IO, earlier source preparation and engineering tests are outside
that stage sum; electrical energy and full-system cost remain unknown. No process
exit status is counted as business success.

## Evidence and reproducibility

`originals.tar.gz` contains 520 members: 519 original files and their archive
manifest. Its SHA256 is
`bb42d6353d4865c92790948473dcacedd626d160dd2e50cf2e94f7a66f258476`.
Every original member was checked against its recorded SHA256 after transfer.
`EVIDENCE_INDEX.json` binds all requests, model outputs, verifications, training
steps, model manifests, source freeze, owner source and stage receipts. The final
owner checkpoint also verifies all 469 retained files, including model adapters.

The two 2,193,720-byte adapter tensors remain in persistent remote storage and
are listed as excluded archive members with exact SHA256:

| Objective | Adapter SHA256 | Model manifest digest |
| --- | --- | --- |
| Final-only | `8b1af8fac79c32b2456c4d1d23bd8662d736ebb191061a407a61076cb7286d54` | `46c1a35887fc0639050210a19ec2a3a421e1bdb3d5e58cff394a1e54879f29f2` |
| All-actions | `8983207ec254dd74ce69141f8797672af2dc8fd131e2d638fadbb010022bfea9` | `430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786` |

Persistent root on `desktop`:
`/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/retained`.
The runtime artifact root remains
`/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-matched-info-20261118-2e9b`.
The immutable source directory is the sibling `source` directory of the persistent
root. The durable job is `1a1eee74a04-ffbe-36f`; its authoritative terminal state
is succeeded, exit code zero, no timeout, and complete durable output. Its shared
GPU lock was released after completion.

To reproduce the readout, extract the archive into an empty directory and run:

```sh
python3 qualification/cell-matched-info-20261118/readout.py \
  /path/to/originals/retained /path/to/originals/owned-run-1
```

This checks all 96 raw call bindings and outcome aggregates before emitting the
readout. It performs no generation, training or new qualification.

The six upstream tasks come from three exact public repositories and two
maintainer groups, evaluated with the existing `repo_patch` v1 verifier. They are
development diagnostics, forbidden to training; pretraining overlap remains
unknown, and they do not establish independent users, independent evaluation or
external teachers. New source-level diagnosis or future protocols must keep this
completed candidate and its negative results unchanged.
