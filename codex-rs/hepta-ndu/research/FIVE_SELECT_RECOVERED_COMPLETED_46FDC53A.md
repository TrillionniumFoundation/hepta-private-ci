# Completed same-source SELECT followthrough: no selective-answering gain established

2026-10-14. Executed source46fdc53a0faa0ddec5c264e14b1102cc60e651c6.
Run38520560326 completed SUCCESS in both jobs:115709043006 (contracts/dependency)
and115715713312 (official regression and conditional model followthrough).
Full decoded main-job logs and both final job statuses were read. Actual model
download and inference steps succeeded; this was NOT a deferred contract-only
success. This note does not run a model or change any old score or model owner.

## Executed work

Main official-model job:567 passing test invocations,564 distinct identities,
zero skips. Counts by suite:14 matrix,54 protocol,29 native,61 Group,28 response,
33 adapter,17 Encoder,26 paired,25 source-time,25 fit-audit,20 projection,
27 content-swap,31 SELECT inventory,36 answer review,29 question relevance,
57 SELECT-question,25 recovery and30 origin. Three NativeAdapterTests imported
by the paired suite repeat. The preliminary contract job separately succeeded;
its repeated checks are not added as new distinct tests here. These are focused
Python/HF checks, not a full repository/Rust or task-quality qualification.

The exact successful recovery38518485794/source61e909b2 and its unique artifact
11873917916 were used. Original cancelled38512395172 remains CANCELLED. Saved
model composition, adapter tensors, base immutability and frozen state checks
passed for all four candidates. No new model selection or training occurred.

The fixed matched-question requests were generated12/12 successfully, totaling
334 actual generation decoder forwards. Four-score diagnostics cost48 additional
forwards (12 per candidate). Old mismatched answers were reused verbatim, not
regenerated. Original four recipients remain:three have available/scored pairs,
one has unavailable annotation/donor. Repeated candidate evaluation does not
turn these into12 independent tasks. New optimizer updates0, formal reviews0.

## Actual same-source/different-question results

The interaction compares the SAME donor answer/refusal targets under matched
and mismatched questions on identical nonempty evidence. It is different from
the prior own-answer/donor-answer content-swap interaction. Values are mean-token
log-probability contrasts, not correctness probabilities or semantic grades.

| Saved candidate | Mean interaction | Family-macro interaction | Both weak likelihood directions positive | Selective generation pairs |
| --- | ---: | ---: | ---: | ---: |
| Frozen Reader |0.2527013719|0.1696293727|0/3|0/3|
| Repeat-empty training |1.7961801092|1.4616747797|0/3|0/3|
| Nonempty aligned relevance |0.6544880271|0.6227482706|0/3|0/3|
| Nonempty reversed relevance |0.4599454602|0.4904191047|0/3|0/3|

All candidates have0/3 matched refusals and0/3 mismatched refusals. None meets
the joint generation pattern (substantive nonrefusal matched AND refusal
mismatched) on these available pairs. Positive average interaction alone does
not establish two proper likelihood directions. Aligned nonempty training does
not exceed the repeat-empty control on this interaction summary. There are no
reported semantic accuracy, confidence interval or independent-confirmation
claims. Donor supervision remains weak and exposed development; superficial
question/entity cues and annotation mistakes remain possible.

No candidate is admitted. These results do not show that shared encoders or
small heads cannot learn the relation; they finish the specific saved-Reader
comparison and motivate testing the cheaper representation/readout alternative.

## Retained source and costs

Main artifact11875865464:
hepta-select-recovered-followthrough-development-check-disposition.
GitHub-reported1,519,951 bytes/520 files. SHA256:
380c48d91885040147a31847c49429af7a75f96bd22274baad94bb435327acd0.
New raw answer SHA256:
f39ff03e356d4922e9b3ddd50cde26aabe7dc77c8237e6b778175ea965c16bad.
Plan SHA256:
f6a75a2d08ccc2e46fadff85fb23f347b98adcad975145d982285fc6b6b7cc80.
Upstream recovery origin SHA256:
65d8b5dd7b54ef83a5d0a0a8ffb3aad5b0645d9a5fbe02e8448c714788cfc104.

The logged execution disposition explicitly has dependency_ready=true,
model_report_exists=true and model_execution_completed=true. Reader adequacy
and production acceptance remain false. Whole archive and member validation
ran on the hosted worker. This turn's local runtime was unavailable: output
archive metadata and hosted verification are NOT a claimed local ZIP rehash.
Loading, staging, replay validation and repeated tests cost resources. Actual
energy/FLOPs and matched lifecycle cost superiority are not established. Recovery
and old cancelled-prefix work remain upstream additional costs, not free reuse.
