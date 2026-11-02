# R22 certified control directions

R20's failed finite-step tests are preserved. The new bounded result is a certified local directional solver for the declared fixed mesh, with a genuine one-ulp branch-selection repair. All156 fresh nonconstant signed directions,20 exact/near-tie whole-array cases and8 negative controls pass. Arbitrary ties, continuum/full gradients and production adoption remain open.

| Evidence | Result | Meaning |
|---|---|---|
| Original R20 finite steps |30/78 both;71/156 individual|Original gate remains FAIL|
| V1 retrospective local diagnosis |78/78; max analytic discrepancy1.3323e−15|Old sample derivatives were local-correct; finite steps cross policies or incur truncation|
| V1 adversarial verifier probe |Two corrupted initial-left arrays accepted|Actual input-validation hole; V1 sources/results preserved|
| V2 fixed old engineering cases |3/3|Repair revalidation, not fresh evidence|
| V2 fresh nonconstant directions |156/156|Six new profiles; both signs of all13 controls|
| Binary nonconstant oracle |20/20;10 policy repairs;4 true ties|Whole-array rational oracle; zero derivative discrepancy|
| V2 negative controls |8/8|Includes exact +0.5 initial-left value/tangent corruptions|

Fresh maximum primal enclosure error is **1.9473465540335798e−14**, derivative enclosure error **1.6161926705702406e−12**, and independent analytic discrepancy **1.2490009027033011e−15**. Both enclosure gates use the unchanged1e−10 threshold. The frozen standalone checker replays **1,564,944** fresh/oracle derivative positions, plus30,012 engineering and780,312 V1 retrospective positions; these counts include repeated engineering positions. It verifies all archives, complete arrays and exact rational injections, without importing the solver. It does not independently rerun interval/LAPACK implementations or every rejection summary.

The old largest finite discrepancy remains1.2711191807740496. Its first certified affine switching radius is6.903163921431289e−6, smaller than both unchanged steps1e−4 and3e−5. All156 old step errors decompose into frozen-policy and policy-switch components with maximum algebraic residual2.960594732339136e−16. Components exceed the old tolerance in58 and34 step comparisons respectively; these counts can overlap. No smaller real step was selected.

The correction treats supplied binary64 inputs as exact real constants, not the discontinuous rounded instruction map. Outward residual/slack intervals establish strict policies; a second directional solve repairs a rounded max choice and is recertified. An explicit nonconstant binary family proves true max ties; unknown genuine ties reject admission. R20's real fixed-step gate is not relabeled. Eight affine controls have proved local step radii; nonlinear controls receive a local derivative claim only.

V1 completed the old roster before the omitted initial-left maxima were discovered. Its builder always initializes left/right arrays equally, so those executed records remain usable, but adversarial corruption exposes an actual verifier hole. V2 is a separate namespace, includes both initial-left maxima, strengthens admission with primal accuracy at the same tolerance, and adds two exact binary corruption controls. Seed/N/mesh/steps/tolerances were unchanged and the fresh seed was unopened until V2 publication. The independent source reviewer explicitly records having missed the V1 hole; its V2 review is postfreeze/after launch and examined no fresh arrays.

All13 controls have nonzero whole-array derivatives in every one of their12 signed/profile attempts:

| Coordinate | Nonzero attempts | Minimum/maximum sup norm |
|---|---:|---:|
|sigma|12/12|0.0386996 / 0.0560552|
|wait_cost|12/12|0.285742 / 0.5275|
|recovery_cost|12/12|0.530864 / 0.772921|
|reset_x|12/12|0.130417 / 0.175422|
|reset_fee_0|12/12|1.10784 / 1.35668|
|reset_fee_1|12/12|2.54249 / 3.67831|
|retention_0|12/12|0.178477 / 0.295186|
|retention_1|12/12|0.348894 / 0.692582|
|reward_base_0|12/12|1 / 1|
|reward_base_1|12/12|1 / 1|
|reward_amplitude_0|12/12|0.966389 / 0.993198|
|reward_amplitude_1|12/12|0.966389 / 0.993198|
|reward_slope|12/12|0.103154 / 0.184635|

The11 saved outer child-family receipts sum to **346.537482 CPU seconds**. V2 fresh confirmation itself costs217.446056 CPU seconds (217.727310 wall). This includes startup, imports, input checks and output serialization; inner timing is nested. Earlier/manual engineering, reporting, transport and peer reasoning are not fully metered, so total investment is unknown and the sum is a lower bound. GPU, energy and simultaneous family peak RSS are unmeasured.

Historical reproduction availability is explicitly incomplete. Before fresh launch, checkpoint **c21de56597fc60857b179c8422b0108d5ef7c61b** published/read back the17 V2 source/protocol/dependency files plus their freeze, and committed all184 input hashes. The V1 new diagnosis bytes were local and startup-verified, but not yet remotely delivered; V1 checkpointa921 had only source/freeze bytes. Thus **complete fresh-checkout availability and all-input byte readback before launch are FALSE**. Fresh calculations do not consume those old diagnosis bytes beyond identity checks. Final delivery can restore current reproducibility, not rewrite that history. Restore baseline R20 inputs, then full V1, then V2 before using the frozen reproduce commands. Final remote artifact readback belongs to the root delivery receipt; it is not asserted by this local report.

No full-gradient, arbitrary-tie, moving-boundary, continuum, independent D−B contribution, production or multimodal adoption gate is closed by this component.
