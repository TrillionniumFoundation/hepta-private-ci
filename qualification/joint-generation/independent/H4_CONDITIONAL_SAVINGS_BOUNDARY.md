# H4 supplement: a conditional necessary runtime saving

This is algebra on the already published H4 TRAIN arrays and original T11 cost
receipts, not a new measurement, model fit, qualification result or timing retry.
The immutable [H4 report](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee74daffcdeb9b3f9e5ecad83c6770424d4275ed/qualification/joint-generation/runs/codex-cloud-dynamic-train-headroom-h4/REPORT.md)
and every original result remain unchanged.

Fix all of the following: the current NC full/low potential content distributions,
the selected static NDU/full weights; equal seed/source weights; the original
whole-arm build costs NC8537556029 ns and N8307966292 ns; three seeds;
H100000 requests per seed; reference R73435.296875 ns; and linear CPU price0.02.
The free label-aware rowwise raw oracle is still below NDU/full by
D=0.00021338087227628004 on the empirical equal-seed TRAIN mean.

For an input-level selector/mixture of those two fixed conditional NC laws,
let r>=0 denote its raw
regret relative to that empirical oracle and let S be the **actual complete
runtime** saving per request against NDU/full, averaged with the same weights.
All recurring preparation, routing, generation, encoding and serving costs must
be in runtime. Preserve the original whole-arm training charges; do not add the
critic build twice. The corresponding complete raw CPU-net contrast is

    net_dynamic - net_static
      = -(D+r) - price/R * ((B_NC-B_N)/(3H) - S).

Consequently, even the r=0 free content oracle needs

    S >= D*R/price + (B_NC-B_N)/(3H)
      = 783.484385... ns + 765.299123... ns
      = 1548.783508... ns/request
      = 1.548783508... microseconds/request

to reach zero net contrast. A strictly positive contrast needs a strictly larger
saving; actual raw regret adds r*R/price. This is a conditional **necessary**
break-even threshold, not a sufficient success criterion or independent
generalization evidence. It does not use the nonadditive medians in H4's cost
proxy, and supplies no evidence that this saving is attainable.

In particular, selection is based on the input and any randomization independent
of the potential output realization. A new policy that sees a sampled draft and
keeps/revises it depending on its realized content can induce different
conditional output laws. The rowwise maximum of the two unconditional expected
utilities does not automatically dominate that process; its joint kernel and
oracle must be derived again. This is not a bound on the richer draft-feedback
architecture, nor on the content group's reconciliation study.

The scope is important: changing weights, potential actions, build costs, serving
horizon, reference or price requires recomputing the bound. It is not a bound for
every static policy or another architecture/task; a stronger static comparator
can make the target harder. A policy that avoids original build expenses has a
different comparison and cannot inherit this fixed-build number. Do not subtract
the original critic charge again or regard negative measured timing increments
as free computation.

The decimal derivation is retained in
[the arithmetic receipt](../research/clevr-feasibility-20261023/h4-necessary-savings.json).
This supplement does not authorize further full/low critic search or timing.
