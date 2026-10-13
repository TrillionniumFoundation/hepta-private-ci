# Real Qwen strong-RAG closure — 2026-10-12

**Disposition: real reader execution and read-only replay succeeded; parametric MemoryCell learning, independent semantic claims and production promotion are NOT qualified.**

## Immutable evidence

- Generating source [`6304b451`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6304b451268c73f3d1a605985226b102df841bbf), [Actions run #38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900) (attempt 2, 2026-10-12).
- All three jobs `experiment-format`, `reader`, and `independent-replay` returned **success**. Real original Qwen2.5-3B-Instruct research revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`; no model/precision substitution or training.
- Real Qwen [reader artifact #11743043427](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11743043427), SHA-256 `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`.
- [Separate-process replay artifact #11748040166](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11748040166), SHA-256 `2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071`.
- Original inputs ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`. The complete manifests validated **35 original + 43 reader + 8 replay = 86 member hashes**. The archived answer/receipt census had **40/40 calibration + 72/72 evaluation** actual generations, and the independent replay passed all 112 original answers.

## Frozen reader results (eight *authored and previously exposed* questions)

| Qwen fixed arm | Strict correct | Correct with all program-declared chain sources cited | Input tokens (eight calls) |
| --- | ---: | ---: | ---: |
| Calibrated top-1 | 5/8 | 3/8 | 3,961 |
| Hybrid top-4 | 3/8 | 1/8 | 10,806 |
| Hybrid top-6 | 2/8 | 0/8 | 15,463 |
| Hybrid top-4 reversed | 3/8 | 1/8 | 10,806 |
| Single hop | 4/8 | 4/8 | 4,575 |
| Entity/time full path | **8/8** | **4/8** | 5,752 |
| Organized / explicit correction pruning | **8/8** | **4/8** | 5,179 |
| Program-specified support (not a human oracle) | **8/8** | **4/8** | 5,179 |
| Empty evidence | 0/8 | 0/8 | 1,630 |

Calibration `k=1,2,3,4` all had 4/8 strict success, so **k=1 was a cost tie-break**, not a superior task-accuracy choice. Removing one of eight calibration questions changed the winner to k=2. The selected k=1 test arm had **two correct responses lacking the full program-declared supporting source set**.

**Paired effects:** k=1 versus hybrid top-4: +2 task wins (2/0/6); full-path versus single hop: +4 (4/0/4); organized versus full-path: **0** (0/0/8), with only **573 input tokens saved (9.96%)** by organization. The actual saved seconds cannot be presented as deployed lifecycle ROI. **39 pairs** of identical question + ordered evidence showed no answer/token disagreement.

### Qualification decision

The 4/8 full-chain citation figure is a **structural, authored-program support check**; it is *not independent human semantic entailment*. No independent future source family, verified 99% citation precision, amortized lifecycle cost, or learned/parametric gain was measured. The archive reports `production_accepted=false` and `candidate_accepted=false`. Neither a successful workflow nor 8/8 task answers authorizes admission.

The machine-readable record [`strong-rag-38224780900-disposition-summary.json`](../../scripts/memory_cell/data/strong-rag-38224780900-disposition-summary.json) retains the exact SHA pins, nine arm scores and explicit rejection flags. Six model-free tests in [`test_real_rag_disposition.py`](../../scripts/memory_cell/test_real_rag_disposition.py) reject inconsistent summary metadata; these tests alone do not constitute a second semantic review.

**Next real experiment:** same frozen reader/encoder/evidence, compare unchanged prompt with a pre-registered explicit *full-source-chain citation instruction*, then require fresh independent source families and human sufficient-context adjudication. Only promote a learned Head if it beats the strongest eligible deterministic full-path/filter baseline at matched total cost. Do not loosen `blocking-ci` or turn the research Qwen checkpoint into a production serving model.
