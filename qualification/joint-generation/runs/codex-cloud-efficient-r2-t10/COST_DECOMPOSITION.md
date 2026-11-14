# Independent T10 cost audit

T10 exited2, selection_ready=false; actual caps held and formal test remains unopened. This audit reads existing selection/build receipts only. All five build ledgers/costs agree with selection; source/freeze/receipt hashes are bound in JSON.

| Contribution to NC minus N complete CPU-net utility | Mean |
|---|---:|
| Full-view content gap | -0.003445684603 |
| Same-NC-weight routing | +0.000446690712 |
| Service CPU price | +0.000063314174 |
| Complete build CPU amortization | +0.000285346056 |
| Preparation CPU amortization | -0.000000035657 |
| Reconstructed total | -0.002650369319 |
| Recorded failure contrast | -0.002650369319 |

The identity closes within4e-16. Raw gap is−0.002998993892; complete CPU pricing contributes+0.000348624573. All random probabilities are1, so random is NC always-full. Routing is negative for seeds11/23 and positive for47; its mean alone does not establish heldout benefit.

| Seed | Content gap | Routing | Complete CPU term | Complete net | N/NC final updates | NC decision price |
|---|---:|---:|---:|---:|---|---:|
| 11 | -0.006840221 | -0.000119279 | +0.003786063 | -0.003173436 | 636/490 | 0.000000000000 |
| 23 | -0.008473628 | -0.000250254 | -0.002474297 | -0.011198179 | 637/475 | 0.007357243374 |
| 47 | +0.004976795 | +0.001709605 | -0.000265893 | +0.006420507 | 637/402 | 0.000000000000 |

NC full content lags N for11/23 but leads for47 despite fewer updates. The decomposition is descriptive, not proof that more updates would remove the gap. Full per-seed costs, useful updates, prices and raw calibration deltas are preserved in JSON.

| System | CPU /10s | Units /12B | Unit-stop /CPU-required candidates | Residual rounds | Residual stop |
|---|---:|---:|---|---:|---|
| additive | 9.756826697 | 11923377005 | 6/3 | 80 | CPU forecast/guard |
| anchor | 9.026515026 | 11997736703 | 7/2 | 14 | unit reserve |
| ndu | 9.766629212 | 11564568321 | 6/3 | 123 | CPU forecast/guard |
| ndu_control | 9.351370447 | 11052490314 | 0/9 | 20 | CPU forecast/guard |
| supervised | 9.067202295 | 11995440577 | 8/1 | 3 | unit reserve |

**The limiter changed from T9.** All9 NC candidates stopped while units still admitted the next conservative envelope, so CPU guard was necessary. Selected NC search updates470/455/382 compare with N513/514/514; selected N next steps were unit-rejected. NC ran20 residual rounds and N123. At residual-loop termination A/N/NC still passed their unit condition; CPU forecast/last-step guards prevented another round. S/H failed the unit condition. Not every final last-step clock is saved, so an exact final CPU-guard value is not invented.

Restoring the stop ledger by adding the subsequently executed changed-model validation gives N597,375,519 units against168,926,598 required, and NC1,451,487,051 against529,179,051 required. Actual final unused units are435,431,679 and947,509,686 respectively. These cannot override the frozen CPU guard/forecast; no actual CPU-cap failure occurred.

In all five arms, both search/refinement counters satisfy full+low rows=64*updates, one logical forward/backward per update and each144*h*low_rows MAC reduction. Actual prices match the algebra exactly; sums of actual candidate/refinement deltas reconcile with their ledger stages; forecast rates use actual units. The componentwise envelope is admission-only and is not charged. Shared dense500 base pretraining remains unchanged.

Smallest deterministic reuse: MixedEncoderBatch currently gathers self.x[self.full_indices] separately for forward and backward. Reuse that same subset within one batch while preserving all-full behavior, math and RNG. This eliminates one duplicate materialization, with no invented arithmetic-unit saving; CPU gain and sufficiency are unmeasured. A larger once-per-arm immutable low-row packing cache would need billed setup and independent review, and is not implemented here.

Runtime evidence records one process task and one actual BLAS thread with the captured NumPy/backend identity; it does not prove absence of transients. No source/run/test file was modified. An initial administrative summary exited1 because archived T9 selection was unavailable; this final audit removes that dependency and uses T10 only.
