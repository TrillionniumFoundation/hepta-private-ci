# Publication notes: producer evidence and independent review attempts

The final independent semantic review is **`independent_semantic_review_r3/REVIEW.json`**, with status `PASS_WITH_SCOPE_LIMITS`. Its accompanying `REVIEW.md` explains the independently executed mathematics and limits. **The root `REVIEW.json` is a preserved failed r1 artifact, not the final verdict.** It is retained unchanged and is byte-identical to `independent_semantic_review_r1/REVIEW.json`.

The original producer package contains 40 manifest-listed files plus `PACKAGE_MANIFEST.json`, totaling 41 files. They remain unchanged. The original manifest SHA256 is:

`292d2cb40fef4ce3eb633440d8e7d4059eed0b1a632d399d59658ccba1503b9e`

`PUBLICATION_FILES.json` is the explicit relative-path whitelist for the complete publication. It includes all producer files, review plans, all three reviewer scripts, successful and failed process receipts, stdout/stderr, the preserved root failure artifact and these publication notes. It excludes `__pycache__` and does not delete, rename or rewrite historical files.

## Review attempt history

| Attempt | Result | Retained evidence | Explanation |
|---|---|---|---|
| r1 | FAIL; process exit 1 | `review_semantics.py`, `REVIEW_PLAN.json`, `independent_semantic_review_r1/`, root `REVIEW.json` | The review loader merged task and deployment namespaces and overwrote the task schema. This was a reviewer defect. No producer source, result or tolerance was changed. |
| r2 | No successful report retained; process exit 1 | `review_semantics_r2.py`, `REVIEW_PLAN_R2.json`, `independent_semantic_review_r2/` | The corrected namespace loader reached report publication, where exclusive creation of root `REVIEW.json` failed with `FileExistsError`. This attempt cannot be counted as a completed successful review. |
| r3 | PASS_WITH_SCOPE_LIMITS; process exit 0 | `review_semantics_r3.py`, `REVIEW_PLAN_R3.json`, `independent_semantic_review_r3/` | The same declared numeric checks and tolerance were rerun with a unique report path. This is the final retained independent verdict. |

The final reviewer independently recomputed all 2,880 endpoint/first-hit comparisons through transient-submatrix survival, and the two outer first-hit causes through transient flux. It separately solved the full CTMC and entry/reset-count ODE for the first listed TRAIN world of each fit. The largest reported absolute residual across its checks is `1.3145040611561853e-13`. These are numerical checks, not outward-rounded proofs.

The review also confirms that equal latent mass/bank after same-tick WAIT/REPAIR does **not** mean that REPAIR has no model or behavioral effect. In all 320 comparisons, READ becomes legal again and the downstream predicted Q and Belief change because public sensor/fee features change. The narrow established conclusion is that REPAIR is sensor restoration, not a commanded latent reset.

First-hit calculations include the event atom at time zero. The 960 world/threshold combinations have initial hit probabilities 0 in 219 cases, 0.5 in 522 cases and 1 in 219 cases. Endpoint/first-hit differences therefore cannot be attributed entirely to reset. The original endpoint target remains valid for its declared purpose.

## Complete measured child-process cost

| Phase | CPU seconds |
|---|---:|
| Producer freeze, diagnostic and independent record check | 2.247689 |
| Independent semantic review r1, failed | 0.701608 |
| Independent semantic review r2, failed publication | 1.101085 |
| Independent semantic review r3, successful | 1.084101 |
| All three semantic review attempts | 2.886794 |
| Combined measured child-process total | **5.134483** |

The total was read back and added from all six `PROCESS_RECEIPT.json` files; the two failed reviewer attempts are included. Nested body timers were not added. Controller imports/final receipt writes, publication packaging, agent/editor work, historical training and energy remain excluded or unknown. This is diagnostic/review cost, not an equal-quality training-replacement speedup.

The original `COSTS.json`, `QUALIFICATION.json`, producer README and manifest are historical producer snapshots and were not rewritten when the later review arrived. In particular, the producer's statement that its original record checker did not rerun the CTMC remains true; r3 is a separate, later semantic reexecution with its own sources and receipts.

All results cover five reused research checkpoints and 320 original TRAIN initial states. No independent new validation/test world, new training fit, useful weight repair, Pocket4 production change or live trading benefit is asserted. This publication preparation performed no new experiment and made no GitHub write.
