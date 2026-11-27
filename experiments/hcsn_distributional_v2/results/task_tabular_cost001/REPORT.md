# Supplementary cost audit of the registered tabular task planner

**This addendum was produced after the original five-policy panel was observed.** It extends the original cost calculation to the already registered tabular Bellman reference. The original learned-head cost report, its negative result, every policy, selected threshold, checkpoint and heldout sample remain unchanged.

The ordinary reference, selected on validation before the original fresh-test access, is **validation_schedule**.

| Scope | Tabular task planner | Ordinary reference |
| --- | ---: | ---: |
| Actual native mean utility, 16 three-task streams, macro over three prices | 0.88972917 | 0.57550000 |
| Measured actual execution CPU per stream | 0.188940 s | 0.235835 s |
| Component-allocated one-time research/setup CPU | 87.418699 s | 85.455869 s |

The previously registered 128-stream counterfactual quality panel gives paired tabular-minus-ordinary reward **0.11673958**, with nominal descriptive stream-bootstrap interval **[0.04149857, 0.19193372]**. This interval belongs to the full counterfactual quality panel, not to the smaller actual-native cost panel.

The tabular point estimate remains higher in **24/24** original-grid cost scenarios. The complete cost-adjusted native difference ranges from **0.31366854** to **0.31469793**. The two allocations respectively charge measured method components, or charge the whole new campaign (including the failed first attempt) to the tabular alternative while granting the ordinary reference free new setup. Complete historical backbone training, teacher fitting/solving, actual runtime and complete recovery verification are included in their stated scopes.

These are sensitivity calculations, not measured dollars/energy or a fresh statistical confirmation. The native panel has 16 streams, the classifier is a single frozen v1 backbone, and confidence bins form an approximate Markov state. The direct planner stores fitted transition/reward tables and uses dynamic programming; its capacity and setup differ from the 66-parameter heads. A successful reference planner does not establish an advantage of financial J/G neural operators, v2 distributional content, or the compressed value head.

The original learned value head remains below the ordinary reference and wins 0/24 original cost scenarios. Keeping that negative result alongside the positive planning reference identifies a concrete remaining problem: compressing/learning the useful finite-task policy without losing its reward behavior.
