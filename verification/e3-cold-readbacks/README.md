# Offline comparison of fixed versus learned top-1 routing

A second hosted job regenerated both registered panels from source and rescored every saved cold prediction for all seven arms across three elicitation procedures. On each unmodified archive, it checked the ZIP SHA-256, the SHA-256 of the contained student checkpoint against the pre-confirmation freeze receipt, full coverage of 180 unique evaluation IDs per arm, the zero-byte loopback-only receipts, and the published total, pair and old-skill counts. The compact incremental comparisons below match the individual archive predictions.

| Elicitation | New single questions won by switching to sparse | New single questions lost | New pairs won | New pairs lost |
| --- | ---: | ---: | ---: | ---: |
| Counterbalanced letters | 28 | 15 | 2 | 7 |
| Native yes/no | 13 | 12 | 1 | 5 |
| Native candidate answer likelihood | 5 | 5 | 1 | 0 |

There were 120 holdout questions and 24 reserved pairs per experiment. Each route also passed the same 12 old checks. The fixed policy received the task-family label and selected a fixed teacher's trained expert according to 72 labeled discovery questions. The sparse policy learned a separate text-only selector with the same discovery truth. Each query involved one expert, with one additional linear gate evaluation for the sparse policy. Measurements include cold load plus 180 predictions per arm.

| Elicitation | Student vocabulary features | Preselected single expert | Fixed wall time (ms) | Sparse wall time (ms) |
| --- | ---: | --- | ---: | ---: |
| letter | 1501 | t5 | 11.99 | 12.94 |
| native | 1501 | smol | 9.43 | 10.23 |
| completion | 1639 | smol | 13.12 | 14.07 |

The completion panel's teacher-paired exact two-sided test on 20 held-out questions gave p=1.0 for addition (Smol-only 7, FLAN-only 6), p=0.00098 for agreement (FLAN-only 11, Smol-only 0), p=0.0117 for French (10 vs 1) and p=0.453 for German (5 vs 2). These are unadjusted post hoc diagnostic p-values across six chosen domains. With a simple Bonferroni threshold of 0.05/6, only agreement clears the threshold on this panel. Inferences remain limited by the authored prompts, repeated concepts and small number of template families.

[Verified run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45172184745) · [Paired counts and panel checksums](paired.json).
