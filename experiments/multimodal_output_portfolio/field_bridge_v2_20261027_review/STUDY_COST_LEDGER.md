# V2 study cost ledger

This ledger counts shared work once and retains the cost of inactive preparation and the interrupted primary attempt. It uses completed receipts only; it does not read primary deployment rows or use outcome statistics. The full machine-readable ledger includes every source path and SHA-256.

| Stage | Gradient forward/backward calls | Gradient examples | Other declared work |
|---|---:|---:|---|
| Shared pilot: 18 completed candidates | 2,700 | 172,800 | 162,432 hard-value forward examples |
| H7 fit: 864 complete branch sets | 27,648 | 1,769,472 | 1,769,472 individual branch labels |
| H7 audit: 864 complete branch sets | 27,648 | 1,769,472 | 1,769,472 individual branch labels |
| H7 predictor search | 0 | 0 | 1,440 CV fits +9 final fits =1,449 |
| Inactive D1 replay | 6,912 | 442,368 | 864 inherited fitting states; no new branch labels |
| D1 extra next-gradient measurement | 864 | 55,296 | 2,592 additional probe reverse calls; no optimizer update from measurement |
| Ordinary final path reuse | 0 new | 0 new | 864 logical gradient calls already in H7 fit; 15,360 new selection-scoring examples |
| New field/generic/richer final training | 2,592 | 165,888 | 9 paths; 324 predictor decisions |
| Runtime banks and readouts | 0 | 0 | 138,240 scored actions; 432 heads; 221,184 native ticks |

The listed preparation and final-training stages execute **68,364 gradient computations on 4,375,296 examples**, plus the same number of frozen-teacher calls/examples. D1 adds 2,592 probe reverse calls beyond these training-gradient computations. Actual optimizer-step invocations are recorded separately: 50,172. These totals exclude verification and deployment; they are not a claim about the entire session's compute.

## Shared search and inactive preparation

Pilot search is six recipes on each of three seeds. Its hard-forward count includes the five-action fixed-policy search, original response/clean panels, each candidate's initial and periodic response panels, and final selection/clean panels. The 18 candidate runs all completed. Hard-forward counts are derived from the frozen loop and completed history lengths; gradient examples are also recorded directly.

H7 fitting and development qualification each execute 864 snapshots with four actual eight-step branches. Both phases are charged separately. The nine field/generic/richer predictors share fitting banks; the search is exactly 9×(20×8+1)=1,449 fits. It is not charged once per eventual experimental arm. A fit count does not imply equal arithmetic cost between a ridge and a kernel model.

D1 was not activated: zero real directional predictor fits, zero fresh audit trajectories and zero primary D1 treatments. Its 6,912 chosen-path gradient calls, 864 additional next-gradient measurements, H25 probes and directional forward/reverse work nevertheless occurred and remain charged. Its inherited H7 labels and inherited-parent resource block are references, not a second H7 search.

## Reused ordinary training versus newly executed paths

The ordinary checkpoint is selected from four already completed constant-action H7 fitting trajectories and copied with its complete optimizer state. Its 864 logical gradient calls across three seeds are already included in H7 fitting. Newly executed ordinary selection scoring is 60 hard-forward calls /15,360 examples, with 30,720 reward-observer digit examples.

Each field/generic/richer path still performs 288 gradient and teacher computations. A zero multiplier preserves weights and momentum but does not skip their forward/backward work. Across the nine final paths there are 2,592 gradient calls, while only 840 optimizer-step invocations occur. Their feature/probe and margin work is retained in the JSON; it is not hidden inside the gradient count.

## Runtime fitting

The nine checkpoint-specific banks are generated once and shared by native/history fitting. They execute 27,648 encoder examples, 138,240 transition examples, 193,536 decoder examples and 387,072 reward-observer digit examples. The 432 heads comprise two representations, two families, four transforms, three penalties, three seeds and three checkpoints. Native extraction executes 221,184 ticks and is reused across families/penalties. These counters describe offline train/development search, not selected deployment work.

## Completed scientific deployment

The recovered, frozen evaluation contains **84,480 scientific rows** across eleven arms, three seeds, four test conditions and the declared retention condition. It generated and read back 506,880 logical PNG/UTF-8 media references. Exact-byte deduplication retains 108,793 physical ZIP members containing 91,662,356 payload bytes; it does not reduce logical generation work. Each seed contributes 28,160 rows.

| Deployment event | Count |
|---|---:|
| Encoder examples / batches | 84,480 / 2,640 |
| Transition examples / batches | 132,066 / 7,761 |
| Decoder examples / batches | 253,440 / 7,920 |
| Public preview observer digit examples | 337,920 |
| Additional postdecision reward/audit digit examples | 337,920 |
| Total observer digit examples including final scoring | 675,840 |
| Actual native ticks | 61,440 |
| PNG writes / reads | 253,440 / 253,440 |
| UTF-8 writes / reads | 253,440 / 253,440 |
| Executed unchosen final continuations | 0 |

Deployment event totals are recovered from resource means multiplied by the measured row count in each of 22 disjoint split/arm summaries. All integer sums reconcile within 0.001. Final observer scoring is outside the prepare/finish resource dictionaries: its additional count follows directly from two declared observers, each classifying the two delivered digits. It is explicitly separated from the recorded phase counts. No observer scores, efficacy statistics, primary outcome rows or media contents were read for this ledger.

The three seed jobs ran concurrently, with individual wall intervals from **312.823 to 314.298 seconds**. Duration-only receipts do not identify a common start/end elapsed time. Their durations are not summed as elapsed. The JSON retains weighted resource intervals separately: prepare/finish, neural work, media I/O, decision work, native kernel and evidence storage. Nested or concurrent timers cannot be added as a single end-to-end latency, and no global median or p95 is inferred from group quantiles.

## Verification and recovery overhead

Recorded H7 and final-training replays add 1,168 gradient calls /74,752 examples. Runtime verification adds 276,480 reward-observer digit examples, 221,184 native replay ticks and 432 independent least-squares solves. The arithmetic training audit performs no model forward call; its reported 2,592 new gradient calls describe the already counted treatment, not extra auditing work.

The independent deployment media audit adds **61,440 native replay ticks and 675,840 observer digit examples**, covering all 84,480 original scientific rows and all logical media references. Its 191.321-second wall interval is verification overhead. It performs zero generator forward calls, and its coverage does not create additional generated samples or unique media. Recovery parity additionally compares 11,808 repeated records and 6,560 native receipts without reexecuting the model or native kernel.

The interrupted primary attempt produced **at least 11,808 complete extra outcome rows**: 5,824 for seed17, 3,296 for seed29 and 2,688 for seed43. Its 6,560 preserved native receipts establish **at least 13,120 additional native ticks**. Unflushed or incomplete work is unknown and is not set to zero. Recovered runs are the same registered execution, not a new independent replicate; partial outputs are excluded from the final scientific sample count but remain execution overhead.

Known native study work is therefore at least 295,744 ticks: 221,184 for runtime fitting, 61,440 for scientific deployment and 13,120 from the interrupted attempt. Independent runtime/deployment verification adds 282,624 ticks. Earlier development or engineering benchmarks are outside this subtotal.

Other synthetic contracts, derivative checks, native engineering benchmarks, earlier development diagnoses and original V1/pretraining are not fully metered by this receipt set. The verification subtotal is therefore a documented lower bound, not a zero-cost declaration for omitted work.

## Logical tariff and elapsed time

The objective subtracts 0.002 for the common first refinement and another 0.002 for a non-stop final continuation. Thus stop carries a 0.002 logical charge and non-stop carries 0.004; final decoding still occurs for stop. This tariff is not measured latency, FLOPs, energy or money, and repeated scores must not be summed as a financial bill.

Per-receipt wall and CPU times are preserved. Seeds and stages can overlap on the shared host, so sums of wall intervals are not end-to-end duration or evidence that one treatment is faster. No FLOPs or financial estimates are supplied.

## Evidence

[STUDY_COST_LEDGER.json](STUDY_COST_LEDGER.json) contains per-seed counters, deduplication rules and all input hashes. Principal inputs are the pilot result/protocol; six H7 BANK/COMPLETE pairs; PREDICTOR_FREEZE; three D1 BANK/COMPLETE pairs and NOT_ACTIVATED; final TRAINING_COMPLETE and path resources; nine runtime BANK_IDENTITIES/READOUTS pairs; verification receipts; and IO_RECOVERY_REGISTRATION. The completed append also binds EVALUATION_COMPLETE, RESULT resource fields, all three seed completion receipts, PRETEST_FREEZE, INDEPENDENT_MEDIA_AUDIT and RECOVERY_PARITY_AUDIT. The 35 frozen scientific source files match their pretest and completion identities. No frozen scientific file or archive was modified.
