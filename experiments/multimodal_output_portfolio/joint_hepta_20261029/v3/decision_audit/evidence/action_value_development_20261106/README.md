# R2 development action-value training evidence

The existing transition recorder is now connected to a real numerical SGD trainer. The trainer consumes retained actual public before-views, externally bound development labels and explicitly costed action outcomes. It saves parameter and momentum state and requires both checkpoint and completed-fit receipt identities on cold prediction.

**This evidence contains controlled synthetic backends and labels. It does not report a real independently labelled R2 controller fit, a four-arm comparison or promotion.** Actual tiny-sd development training is separately recorded in the sibling `sd_development_20261106` directory.

## Source and integration

Implementation publication: `7044eac0f5132f894da2de93158f9bf07c86e8ad`. The original A recorder, reader, observer wiring and controls were reused byte for byte. Those five files were published concurrently on PR #4857 at `68564f6fd8414ba5452ad6c6bf37d7cc41c767e8`; merge `c870b1262f91d5c5ccbc172448e6934f302c2175` reconciles their ancestry without changing any execution bytes. The action-value PR therefore adds C on top of the existing A implementation.

`ACTION_VALUE_FINAL.json` identifies the three new implementation/test/document files. `ACTION_VALUE_SOURCE.json` identifies A. Their historical unpublished-dependency wording is retained as an original receipt; the later publication is recorded here and in `QUALIFICATION.json`.

The root's final same-process integration invocation passed **36/36** controls: 13 transition-capture, 5 observer-admission and 18 action-value cases. The exact eight files, final document included, were identical before and after this run. The 18-case implementation run and independent probes are also retained; repeated runs are not added as extra independent fits or scientific samples.

## Independent implementation review

The reviewer reproduced and then closed four concrete failures:

1. Modifying an unpinned FIT status could admit an over-budget checkpoint. Cold loading now checks externally retained checkpoint and FIT digests and their lineage.
2. Finite extreme values could overflow the loss and escape without a terminal receipt. Targets, statistics, updates and predictions now reject nonfinite values and preserve finite partial state and costs.
3. A provider action could return successfully after the episode deadline and receive a positive target. The actual action return and accepted episode outcome are now distinct; final failure requires the explicit failure utility.
4. KeyboardInterrupt during final or partial-state writes could escape the fit. Cancellation now preserves the original cause and cost and never invents a successful receipt identity.

The full original counterexamples, repaired probes, synthetic captures and source snapshots are in `independent-review.tar.gz`. A different agent on the same filesystem is an implementation reviewer, not an independent semantic evaluation custodian.

## Cost accounting

The final 36-case combined run used **5.081776 CPU seconds including waited descendants** and **1.613524754 seconds wall**. These include nested fit/reload work and must not be added to its inner meters. This was a separate invocation from the earlier recorder and trainer controls.

`ACTION_VALUE_COSTS.json` retains all author attempts, including the 16-pass/1-error attempt and its correction. Attempts 2–5 have complete observed envelopes totalling 21.272683 CPU seconds and 9.088467347 seconds wall; attempt 1 has only framework time, so no complete development total is claimed. The earlier A-only invocation is preserved separately. Independent probe envelopes, including unknown CPU fields, remain separate from those test totals.

Energy, physical storage/network traffic, original authoring/setup and complete orchestration/publication costs remain unknown. Explicit null/unknown values are not free work. `EVIDENCE_INDEX.json` separately records archive preparation and readback.

## Scientific boundaries

Features read only the public actual before-view. Declared train/development source clusters, source IDs and exact image hashes cannot overlap; this does not authenticate fresh acquisition or near-duplicate isolation. Missing observed-action labels reject; unexecuted intents remain unlabelled and cost-retained. Public model critique is a feature, never an independent target.

The predictor estimates one-step labelled utility gain less the declared costs. It is not the gamma-2 CE estimand or a proven value-of-information/continuation-Q model. There is no training-resume API, independent semantic quality result, strong-baseline qualification, power result or production adoption. All six confirmatory R2 gates remain open. `no_update=true` means no incumbent promotion; the controlled SGD candidates really do update.
