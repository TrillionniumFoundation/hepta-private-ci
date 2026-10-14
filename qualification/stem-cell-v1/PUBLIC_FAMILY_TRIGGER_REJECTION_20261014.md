# Public pretrained family experiment: split correctly rejected

This evidence comes from **another branch** (#1861), not the fanout code in #1903.
Source head: `b7c09fb20180fd927820f84a4501bfb472e472f9`.
Actual Actions checkout: `87bf717eb37dbf081459d07f952f5f316d4f7314`.
Workflow 38532331059, artifact 11883631981, ZIP SHA256
`a219b8c5c338381a1ac4956450c758a28f635f3db6af26e67a03a2da42ac4101`.

One frozen pretrained ModernBERT checkpoint, 64 training / 64 test AG News items,
5,000,000,000 train-plus-transition formula units per arm, seed 7347.

- `family_direct32`: completed; 47/64 test answers correct; per-category
  9/16 World, 16/16 Sports, 10/16 Business, 12/16 Science/Technology.
- `family_split16to32`: `FamilyBudgetRejected`; reason
  `residual_did_not_trigger_split`.
  The training-only residual **0.0017405797261744738** was below the
  pre-registered split threshold **0.05**.
  Stage one consumed **1,980,702,800** out of **2,000,000,000**
  formula-work units; this work and the failure remain in the denominator.

The split arm did **not** produce a 32-Cell trained candidate or a score.
It is invalid to compare 47/64 directly against a nonexistent split score.
`parameter_matched=false`; `all_arms_completed=false`;
no topology or learning winner is identified.

Do not silently lower the trigger threshold, replay only favorable attempts,
or reinterpret a forced split as residual-triggered. A new **prospectively
registered** fixed-boundary split/no-split comparison, with independent
new evaluation material and complete costs, would test another estimand.
This evidence is not a new experiment run and does not alter the original
failure bytes, policy or historical results. No model or NDU promotion.
