# CTRL 11: recovered original #5450 native readback (2026-11-10)

**Source head:** `f6a7d5307f888d30faa8803d23487c78789b99fe` (#5450). **Readback host:** configured HeptaRuntime operator `ai395`, existing frozen `ndu-portfolio-frozen-20261109-eb02e89/collection-v1`. This is **read-only analysis of the original November 9, 2026 artifacts**, not a new 60-episode experiment or a recreated fixture.

Previous [#5502 qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5502) correctly stated the raw trajectories had not been recovered *at that earlier read*. They were found during this later host readback; the previous snapshot is left intact. The machine-readable, digest-only audit is [ORIGINAL_NATIVE_READBACK_20261110.json](ORIGINAL_NATIVE_READBACK_20261110.json). It preserves six trajectory/launch/delivery/evaluation SHA-256 tuples and diagnostic source/record pins without copying private candidate or reference text.

## Native byte and identity checks

- Frozen collection plan SHA-256 `7be396821d6a16352b5e71b66f0a374962153c269063134ced06b4ce924d9ee6`; original diagnostic JSONL SHA-256 `28411d648b645d3683e3bbcdee7ac6ee9dbef69ad793acc8288d8696bff9c062`.
- Original `readback-export-v1.tar.gz` SHA-256 `f1d10d6d8e9efcb30980a6fb75439b537dfda05a71f39bcfb1f0f20a17e566a2`; its declared 7/7 files pass independent local SHA/size readback. All **60/60** original per-attempt `result.json` files pass their stored byte-length and SHA-256 bindings; all statuses are `Completed`.
- Pinned evaluator Python source SHA-256 `7988cb2eaaf8e3aad6f943fd762a1fd8847b5d44dbdc6eb5330ca2e45fc6ff45`, equal to the frozen plan and all 6 relevant evaluation receipts. The frozen rubric SHA matches all 6 evaluated snapshots. These are host-observed byte receipts, **not** independently authenticated operator or evaluator key attestations.

## Six historical WRITE_TEXT failures: first observable boundary

All six diagnostic-phase `WRITE_TEXT → STOP` cases came from the original collection, each identified through its `episode_id` → original trajectory case ID → per-attempt result path. The persisted `diagnostic-training-rows.jsonl` `split=train` field is a row role, **not** evidence of an independent confirmation set.

| Measured link / statement | Six diagnostic cases |
|---|---:|
| Candidate metadata contains at least one text matching the reference under frozen canonical normalizer | **6/6** |
| Action payload is itself one of the original candidate texts | **6/6** |
| Action payload matches any canonical reference text | **0/6** |
| Original actor exited 0 under enforced isolation | **6/6** |
| Raw actor stdout event SHA agrees with launch host exchanges; decoded wire equals stored trajectory | **6/6** |
| First post-WRITE delivery contains the exact emitted actor payload | **6/6** |
| Subsequent STOP leaves delivered bytes unchanged | **6/6** |
| Pinned scorer receipt and score agree with canonical delivered-text mismatch | **6/6**, text score 0 |
| Original current-format `content_selection` receipt | **0/6** |

**Finding:** the earliest **observable semantic text mismatch** is already present in the actor's `WRITE_TEXT` payload. The actor emitted a nonmatching available candidate despite matching candidate(s) being present; the surviving host delivery and pinned scorer did **not** change those bytes or incorrectly award zero for a canonical-match. This is more precise than the earlier generic unknown. It does **not** identify the internal model-ranking cause, the exact original `selected_index` receipt, or guarantee higher scores from a different untested policy. Retain historical `selected_used=unknown` until selection identity and external owner attribution are independently supported. A candidate's presence is not proof it was selected.

## READ and WAIT original continuation

The **six diagnostic READ_ROI** records are all real `PREPARE_ROI → READ_ROI → STOP` trajectories. For each, all four saved deliveries (initial, after PREPARE, after READ, after STOP) are byte-identical; every corresponding terminal quality is **0**. No answering suffix was executed. Thus these original cases establish **no realized output benefit of READ by itself**. They neither disprove potential informational value with an actual READ+answer suffix nor provide a genuine same-state paired STOP-vs-READ+answer policy experiment.

Across all 60 original trajectories: `STOP=60`, `PREPARE_ROI=24`, `READ_ROI=12`, `RENDER_IMAGE=12`, `WRITE_TEXT=12`, `WAIT=0`. No original WAIT continuation outcome is available.

## Non-promotion and remaining gates

This establishes a **bounded historical actor-payload fault location**, not deployment readiness. The readback host was authenticated for filesystem access but its native owner and independent evaluator provenance have **not** been separately attested here. Original source identity/global exposure, real prospective policy improvement, matched source-independent same-state STOP/continuation action tables, real execution/effect receipts, and full training/tuning/planning/provider/energy costs remain open. No new cloud job, policy update, isolation bypass, advisory suppression, or security upgrade occurred. See [#5605](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5605) for the still-failed RustSec `cargo-deny` qualification.

**Disposition:** `HOLD_NO_GO`, `production_update=no-update`. The six content failures are now localized to the observable actor payload; the internal selector mechanism and all other original CTRL blockers stay unclosed.
