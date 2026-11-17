# Round03 engineering evidence

These are engineering observations and explicit scripted-provider fixtures, not completed GPU experiments or new independent samples.

## Completed observations

- Integrated suite: 37 tests passed, no failures or skips, 16.512 seconds in unittest. Original core64 byte identities are unchanged.
- One subsequent targeted unreadable-receipt regression passed in 0.002 seconds. The earlier 37-test artifact is retained unchanged.
- One earlier actual tiny Qwen2 + PEFT CPU adapter save/load/gradient-update test passed. It does not validate the real 1.5B GPU experiment or the shared pool.
- Source04 lifecycle review independently passed 11 behavior tests; these overlap the integrated suite and must not be added as independent data.
- Current shared-pool A/B/A tensor test, real material backend smoke, formal prepare, new GPU jobs, primary/cold model evaluations and formal Circuit remain NOT_RUN.

## Archives

| Archive | Bytes | SHA256 |
| --- | ---: | --- |
| [circuit-source-and-tests.zip](circuit-source-and-tests.zip) | 24699 | `f698028da71c11bc09fd75ae863ce02fbdb604f91dbf43485ce5320101516d9e` |
| [independent-pool-and-controller-review.zip](independent-pool-and-controller-review.zip) | 53914 | `f9e9eb643a666d36fde880b7a1c80be4c0f6ca500ee1fe27b47c71fb8fa4f3ef` |
| [onpolicy-engineering-evidence.zip](onpolicy-engineering-evidence.zip) | 83698 | `065e2c7b17c4515bc9567bb0b3b0d56134018a913ac5f34bc33e1d0fd6477821` |
| [reporting-producer-fixtures.zip](reporting-producer-fixtures.zip) | 520627 | `fff039f5698d214b4b27421ed1349623c0126f336c5c46b99a6782c63879f02f` |
| [root-engineering-evidence.zip](root-engineering-evidence.zip) | 575686 | `fd16a7fb70813887d28f34ceee4b781c0345c23ab61faf7ece67104617dfec7e` |

`onpolicy-engineering-evidence.zip` contains exact historical source blobs plus public derived views of runtime records. [ONPOLICY_INDEX.json](ONPOLICY_INDEX.json) explains the seven omitted duplicate/internal-URL fields; actual error text, statuses and source hashes remain available. The views are not mislabeled as byte-identical originals.

`circuit-source-and-tests.zip` contains the actual message-graph implementation snapshot and its ten CPU business-verifier checks. `independent-pool-and-controller-review.zip` retains original findings, import-harness failure and correction, corrected source04 review, and reviewed controller snapshots.

`reporting-producer-fixtures.zip` contains the cost-report module, test logs and explicitly labeled actual producer fixtures. Its optimizer and provider receipts are scripted test data. No fixture receipt is a trained candidate.

`root-engineering-evidence.zip` includes integrated and targeted logs, the initial controller serialization failure, the incomplete empty-directory cost readout, transport/format observations and retained producer artifacts. It reconstructs the pre-fix plan by an exact inverse diff and checks its original recorded hash. Its manifest binds every retained member.

## Limits that remain binding

- A6/B3 are old exposed development tasks. Replays, graph variants, seed choices, subagents and cold reloads add zero independent N.
- Equal call/token caps are not measured equal cost. Shared pool loading, search, controls, interventions and extra evaluations have separate scopes.
- E2 student verifier counts omit reference rechecks. Whole-system time, energy, money and reference totals are unknown, not zero.
- Source metadata for Chain issue150 is not an agent trajectory, future task, new teacher or newly admitted training record.
- Host transport is disconnected. The current just fmt request has no execution receipt; no whole-repository CI-green claim is made.
- Scientific confirmation, native Cell/HIA execution, foundation-model capability, production adoption and PoUW eligibility remain false.
