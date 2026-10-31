# Independent review of the completed V2 primary evaluation

The complete registered study is reproducible and its reported arithmetic is correct. **None of the six primary claims passes the joint gain-and-retention rule.** This does not mean that ordinary learning has no benefit: its test improvement is clear under both observers, while its separate retention requirement remains unestablished.

The conclusions below use the frozen [primary protocol](../field_bridge_v2_20261027/PRIMARY_PROTOCOL.json), [primary result](../field_bridge_v2_20261027/evidence/PRIMARY_RESULT.json), and independent verification receipts. No threshold, comparison family, predictor, model, fixed-action fallback or stopping rule was changed after observing primary outcomes.

## Verification completed

The full delivered-output audit covers **84,480 rows, 2,640 batches, 84,480 committed decisions and 506,880 logical PNG/UTF-8 references**. It reopens 108,793 distinct content-addressed entries containing 91,662,356 bytes. Both frozen observers rescore all delivered outputs, yielding 168,960 independently reconstructed score rows. Every public-feature coordinate and every numeric score component matches exactly: maximum discrepancy **0**. Categorical outputs, source identities, model/controller identities, selected actions, operation counts and preview–decision–final ordering also match. All **61,440 native ticks** reproduce their complete non-timing receipts. The verifier performs no generator forward calls.

Separate independent arithmetic covers all six primary contrasts, all nine retention comparisons, fixed-model signs, global certainty equivalents, descriptive interaction and reset action counts. Its maximum discrepancy from the frozen analyzer is **3.2439329000766293e-16**, with identical acceptance decisions. Training verification covers all twelve final checkpoints and complete optimizer states; runtime verification covers all nine profile/seed banks, all 432 fitted heads and all 288 feature matrices. These checks establish execution and arithmetic integrity, not efficacy.

The filesystem fault is a documented execution retry. The original attempt remains intact. Every one of its **11,808 complete rows** and **6,560 complete native receipts** matches its recovered counterpart after excluding timing fields and timestamp-dependent decision bytes. All 219 registered original partial files remain unchanged. Recovery uses the same frozen models, policies, observations, random marks and row identities; it contributes one statistical cohort, not an additional replicate. Repeated partial execution remains additional research cost. Work in an interrupted, unlogged last batch cannot be reconstructed exactly from flushed row counters.

## Primary results

Differences are in net-utility units, after the common and selected refinement charge. Intervals are the registered paired source-pair percentile bootstrap intervals with six-comparison Bonferroni adjustment, nominal confidence 99.1667%. Every accepted gain also requires a positive effect in each of the three fixed models, agreement of both observers, and the candidate's retention condition.

| Contrast | Reward observer: difference [adjusted interval] | Audit observer: difference [adjusted interval] | Gain under both observers | Candidate retention | Joint acceptance |
|---|---|---|---|---|---|
| B − A: ordinary learning | +0.030403 [0.021802, 0.039391] | +0.029622 [0.020574, 0.038863] | Pass | Not established | No |
| C − B: field-guided learning | −0.004013 [−0.009351, 0.001096] | −0.005079 [−0.010761, 0.000344] | Not established | Pass | No |
| D − A: native control on frozen model | +0.004413 [0.001821, 0.007153] | +0.000132 [−0.002326, 0.002502] | Not established | Pass | No |
| E − C: native control after field learning | +0.002455 [−0.000183, 0.005132] | +0.000421 [−0.002413, 0.003395] | Not established | Pass | No |
| E − G: field versus ordinary with native deployment | −0.004375 [−0.009904, 0.000866] | −0.005156 [−0.010691, 0.000311] | Not established | Pass | No |
| E − F: native versus matched history | +0.000127 [−0.001726, 0.001990] | +0.000363 [−0.001625, 0.002377] | Not established | Pass | No |

**Ordinary learning:** B − A is positive in every fixed model under both observers. On retention, B's mean changes are −0.000694 (reward) and +0.000250 (audit), but the adjusted lower endpoints are −0.012566 and −0.011205, below the registered −0.01 margin. This is a failure to establish retention noninferiority; it is not evidence of a loss exceeding the margin. Retention passes for **C, D, E, F, H and J**. It is not established for **B, G and K**.

**Parameter-field increment:** C − B and E − G have negative means, but their adjusted intervals include zero. The correct conclusion is that incremental benefit was not established. These intervals also do not establish a reliable reverse ranking under the registered family. C − B holds the literal deployment action fixed. E − G holds the native fitting procedure and information budget fixed, while permitting separately fitted readouts for the two checkpoints; it measures the downstream-adapted pipeline effect.

**Native control:** D − A improves the training reward observer's evaluation, but that improvement does not transfer to the independent audit observer. E − F provides no confirmed superiority over equally informed history. The near-zero point estimate is not a formal equivalence result: no equivalence margin was registered.

## What the successful development gates do and do not show

The original [H7 gates](../field_bridge_v2_20261027/evidence/H7_GATE_RESULT.json) genuinely pass: held-out trajectory MSE is 3.00344e-5 versus 4.64601e-5 for the best registered constant baseline, and action-selection advantage is +0.001555 with paired trajectory 95% interval [0.001192, 0.001948]. These results establish useful local prediction and action ranking on the registered response panel. They do not establish a better final learning endpoint. The primary results separate those two questions rather than contradicting the development gate.

The supplementary field comparisons are descriptive. C − J is +0.002657 under reward but −0.002022 under audit, so the named H7 summary has no demonstrated observer-robust privilege over generic7. C − K is +0.006188/+0.005732, without a registered multiplicity-controlled superiority claim for that comparison.

Resetting native state changes 5,236 of 6,144 test actions (85.22%) and lowers the mean test return relative to E by 0.006194/0.003500. This verifies that the selected policy uses native state. It does not establish superiority to history: reset changes the state distribution seen by the frozen head, and the raw16 residual remains present for the hybrid controllers selected in seeds 29 and 43. Seed 17 uses pure native40.

## Independence and claim boundaries

There are 512 independent source pairs in primary evaluation and another 512 in retention. They are disjoint from each other and from all 25,000 originally recorded source pixels. Conditions, arms and the three historical models remain paired in resampling. The intervals are conditional on those three fixed models; they do not describe a population of newly trained models, writers or tasks, and percentile-bootstrap coverage is approximate.

**B09's original requirement is not fully met.** H7 fitting and audit use disjoint optimizer trajectories on the same fixed response-label panel. They are not disjoint source-image populations. The fresh primary/retention reservations and frozen access boundary close that portion of B09, while the original source-disjoint trajectory-audit clause remains an explicit deviation. It must not be silently rewritten as satisfied.

A successful low-dimensional empirical predictor is not a sufficient-state theorem, a solved FBSDE/HJB system or proof of the paper's parameter-field assumptions. Native state is a deterministic transformation of the same two public observations supplied to the history reference; any finite-family advantage would concern representation, fitting and cost, not additional intrinsic information. This remains a small MNIST-derived task with local adapters and two runtime events. LLM-scale transfer, long-horizon external feedback and production ownership remain unestablished; authority remains `DENY_ALL`.

## Receipt identities

Paths here are relative to the restored evidence workspace; the repository mirrors selected reports under its V2 evidence directory.

| Receipt | SHA-256 |
|---|---|
| `bridge_v2_primary/INDEPENDENT_MEDIA_AUDIT.json` | `e2fc5a17469e1cba7436ec24b24e766f6b6465533260c99179f7bd78b71bbf6c` |
| `bridge_v2_primary/INDEPENDENT_RESULTS_AUDIT.json` | `5340f2b28bc9e377ee6f3144e99540956485dd92757295527c1a622cbfb78fcf` |
| `bridge_v2_primary/RECOVERY_PARITY_AUDIT.json` | `bfd31950dd73af1f9df160b484f501ef91d18e77b4785b77367ba955b74e0f2c` |

These receipts use the archive gate's expected schemas: media `passed=true`, `rows=84480`, `native_replayed_ticks=61440`; results `rows=84480`, finite `maximum_result_discrepancy`; recovery `passed=true` with exact completion/registration hashes. Durable archival restoration is a separate final verification and is not asserted by this review alone.
