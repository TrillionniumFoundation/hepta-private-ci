# MEM-5: paired choices on exact support and prospective released tasks

Freeze the public selector profile before new task evaluation:
`c9b56f198abd1737a9883326fd0c66f411e46218b126aec1e4b6f4f48e66870e`.
No new fitting, model update, encoder change, OCR change or action-space change.
Both actual policies use bounded memory: 128 entries and 524,288 serialized bytes.
The frozen neural policy consumes original model logits; the public-rule policy
uses the fixed public-feature formula. Every processed observation records both
choices on the very same ordered candidate roster and original 126 features.

Actual policy trajectories can select different ROIs. Shared support applies to
each shadow comparison; it is not assumed across the two complete trajectories.
A shadow text choice never counts as a counterfactual successful final delivery.

Choose ten development source groups with all five task families and four
retention-validation groups with the text/image-complementary family. One
metadata-selected episode group per source gives 54 case pairs / 108 episodes.
Salt is `mem5-fixed-support-20261110-4b3362-v1`. Selection order and paired policy
execution order are hash-determined, before reading reference values. Keep the
same frozen weights, 60-second objective and fixed control schedule. At most two
workers execute; no outcome-dependent retries, exclusions or rule retuning.

Preserve original training/tuning/quarantine exclusions and additionally bind
prior episode plans, including original MEM plan SHA-256
`488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5`.
Exclude every source in those plans and their inherited exclusion lists. This
is source-disjoint relative to the pinned records, not proof of complete or
authentic global exposure history. It is prospective development validation;
sealed confirmation and retention-test admission remain denied.

Primary outcome is full-rubric terminal success over all 54 planned cases in
each actual mode. Independently report initial-correct no-op successes, failures,
timeouts, missing/rejected evidence and bounded UNKNOWNs. At the last WRITE_TEXT
anchor (otherwise final actor decision), report candidate availability and both
shadow choices, stratified by actual mode. Unprocessed STOP anchors remain
UNKNOWN. Do not substitute earlier candidates, pool correlated shadow rows as
independent samples, or call this an independent training repeat.

The original scorer runs after the actor exits. The report rechecks byte/source
bindings and both audit chains before reading released references. Actor and
host CPU/wall, OCR/model/selector/checking work and failed attempts remain in
original receipts; overlapping envelopes are not added. Energy/provider charges
and full lifecycle cost remain unknown without independent instrumentation.

Software qualification requires actual frozen-model/OCR actor execution, host
verification before effects, normal and optimized contract regressions, and
exact-source CI. Scientific and production decisions remain HOLD / NoUpdate;
new real-task benefits, sealed confirmation, authenticated providers and full
owner cold recovery require their own evidence.
