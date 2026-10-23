# D1 saved-artifact cost reservation audit

The single registered execution failed in slot 0, `rowwise-png-v1`, with
`ndu:selected_validation_complete`: **10.022472113 CPU seconds > 10.0**.
Slots 1/2/3 did not execute. The complete original accounting, failure, START,
partial state and frozen source remain authoritative; no cost is removed or
credited back, and this audit does not authorize a D1/formal retry.

Evidence inspected: slot-0 `failure.json`, `ndu-partial-arm.json`,
`partial-build.json`, `shared-build.json`, `telemetry.json` and source only.
Frozen source commit: `525fa87a3e0f7220553fbcc9782df3f2e4b073e8`;
freeze SHA256: `97f83d0e26251546cbaeecbc3b613ee8abe9ed44285352827a555e98ca0246dc`.
The inspected run/refinement/evaluation/training-diagnostic source hashes
matched that saved inventory before prospective repair. No data/model tensor,
inference, training, microbenchmark, bootstrap or new measurement was executed.

## Exact failure arithmetic

| NDU attributed component | CPU seconds |
| --- | ---: |
| Complete shared preparation | 3.866379884 |
| Active candidate work | 5.163151655 |
| Shared candidate scheduler | 0.000355476 |
| Active selected refinement/revalidation/export | 0.579948428 |
| Shared refinement scheduler, settled afterwards | 0.040894753 |
| Selected validation, including evidence retention | 0.371741917 |
| Total | **10.022472113** |

After refinement and its deferred scheduler charge, NDU had spent
9.650730196 seconds: **0.349269804 seconds remained**. The selected-service
forecast was 0.280267116, preparation 0.005679304, and observer arithmetic
0.008327132: 0.294273552 seconds together. The existing floor made the tail
reservation **0.300000000**, while its actual complete phase cost was
**0.371741917**. Underforecast: 0.071741917; remaining slack above the
reservation: 0.049269804; actual cap excess: **0.022472113**.

Declared arithmetic was not the binding failure. Actual selected-validation
units exactly equal the reserved tail inventory, **49,464,000**. The final
ledger consumed 10,112,794,371 / 12,000,000,000 units, leaving 1,887,205,629.

## What the receipts can and cannot separate

There were 3,400 real search updates plus 279 selected residual updates
(93 complete three-seed rounds). Selected terminal counts were 486/467/473.
Search objective-step CPU was 4.429192046 inside 5.163151655 active candidate
CPU. The difference includes RNG/input handling, prefix evidence, setup,
validation, export and bookkeeping; it is not an independently measured I/O cost.

The tail forecast uses calibration batch-service CPU, preparation CPU and an
arithmetic observer estimate (`independent/refinement.py`, `forecast`).
`validate_selected` additionally reloads the model, captures output/RNG evidence,
writes canonical PNG/JSON/RNG ZIP archives, hashes them and records receipts.
`retain_outputs` executes after the measured service/preparation timers, but
inside the honestly billed selected-validation phase. NDU retained 1,916,905
ZIP bytes and recorded 3,072,533 hashed bytes there. There is no separate archive
or complete-call CPU timer in these saved receipts, so the 71.742 ms gap cannot
be attributed uniquely or quantitatively to I/O.

The three saved NDU selected-validation phase CPU observations were
0.114853806 / 0.137329376 / 0.118310166 seconds; their sum is 0.370493348,
with 0.001248569 seconds of surrounding active-phase overhead. GC CPU within
them totals 0.024070977 seconds; seed47 includes a 0.020156374-second pause.
All are actual costs, with no exemption. Boundary observations show one
process thread, zero container throttling delta and zero major faults in these
phases; they do not establish an exclusive causal explanation.

`refine_content` computes its shared scheduler remainder only in `finally`
and then charges the full **0.040894753 seconds** to every arm. Earlier
`admit_round` decisions see active arm CPU but not that already accrued pending
remainder. This is a concrete admission-accounting gap, independent of whether
I/O or GC explains the final tail variation. Removing that charge would be
incorrect; prospective admission must reserve it while final accounting charges
it exactly once.

The failure partial does **not** contain `val_measures`. The completed selected
service reports' original per-batch service/preparation/observer costs therefore
cannot be recovered from this partial or the PNG/RNG ZIPs. They must not be
reconstructed by a rerun. Future partial persistence should retain completed
reports as they are returned, preserving the original failure and its real cost.

## Narrow prospective repairs, without changing this result

Include elapsed, unallocated refinement scheduler CPU in each admission's CPU
argument; do not mutate costs for that reservation or charge it twice. Preserve
the final actual full scheduler settlement for all arms. Save completed selected
service reports in future exception partials. Full-call/evidence I/O forecasting
remains a separate unresolved coverage issue; merely adjusting a floor or
multiplier to clear this 22.472 ms failure is not justified. No budget, price,
gate, mathematical update or RNG law is changed, and no performance improvement
or cached-versus-rowwise result exists because the cached slots never ran.

This also corrects the earlier audit limitation: matching the actual arithmetic
inventory did not prove that the complete CPU tail had been reserved.
