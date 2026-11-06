# Why the frozen 144-cell candidate did not beat myopic VOI

This is a post-result diagnosis of the unchanged earlier experiment. It is not
a revised primary endpoint or fresh confirmation. The original result hash is
`5e3c479a257da5776219227690cdaeef03ee7fb33ee3b0a8c8f69040f1f9d221`.

## A two-step action-ranking identity

Write `S(x)` for the fixed terminal value at a decision history, `Q1(x,a)` for
the value of one query followed immediately by STOP, and `V1` for the optimal
one-query-or-STOP value. For a feasible initial action including its cap, define

\[
C(x,a)=\mathbb E[V_1(X')-S(X')\mid x,a]\geq0.
\]

Stage costs and actual duration are already included in `Q1`. The two-step
action value is exactly

\[
Q_2(x,a)=Q_1(x,a)+C(x,a).
\]

Include STOP as an action with `Q1(x,STOP)=S(x)` and `C(x,STOP)=0`. If `m`
maximizes `Q1`, then `m` is also two-step optimal if and only if

\[
Q_1(x,m)-Q_1(x,a)\geq C(x,a)-C(x,m)\quad\text{for every feasible }a. \tag{1}
\]

**Proof.** After a first query the controller has at most one query left, so
Bellman's continuation is `V1`. Add and subtract `S(X')` inside its conditional
expectation. Comparing the resulting `Q2` values gives (1). After an identical
first action, the two-step DP and receding one-step policy use the same
one-query continuation, filter and tie rule. Thus they agree on every subsequent
history, under any true law, not merely under their fitted law. This last claim
uses the earlier implementation's maximum of two queries. It need not hold at
larger horizons. Exact arithmetic gives the identity; the older implementation
uses floating arithmetic and a declared `1e-12` action tie tolerance.

Positive continuation value alone therefore does not imply an advantage over
receding myopic control. It must change the best initial action.

## Exhaustive partition of the existing fixed cells

| Reason for agreement or disagreement | Cells |
| --- | ---: |
| Deadline 0 or 1 permits at most one effective query | 96 |
| Deadline 4, high fee: both choose STOP | 24 |
| Deadline 4, low fee: same first action and cap | 23 |
| Deadline 4, low fee: different first cap | 1 |

The first row is a structural horizon fact. The next two rows are facts of
the recorded fitted banks, not theorems about all possible fitted kernels.
Together they explain the 143 equal-value cells without invoking a failure of
the DP optimizer. The registered generator did not supply a useful test of
lookahead in most cells, although the original mechanism unit test had already
shown a specially constructed two-step advantage.

The single different choice is `damaging_weak`, seed 431, 256 samples per row,
deadline 4 and launch fee 0.025:

| Initial repair cap | One-step value | Continuation lift | Two-step fitted value |
| ---: | ---: | ---: | ---: |
| 1, chosen by myopic | 0.343692748092 | 0.008248280986 | 0.351941029078 |
| 3, chosen by DP | 0.342595419847 | 0.009400129654 | 0.351995549502 |

The fitted advantage is only **0.0000545204242**. Under the unchanged true law,
the corresponding policy values are 0.336905513000 and 0.332591094938: DP loses
**0.0043144180625**. This is a small estimated action-ranking difference with
an adverse true value, not proof that nonmyopic control is generally inferior.
No kernel, seed, source, old result or primary gate is changed here.

## Reproduce the decomposition

From the repository root, write a new output file:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_decision_relevance_20261106.diagnose \
  --output /tmp/ndu-decision-diagnosis-new.json
```

The script binds the original four-source freeze and result digest, enumerates
every legal first action in all 144 cells, checks the Bellman identity against
the stored fitted policy values, and checks the old bytes again afterwards.
The [receipt](evidence/diagnosis.json) is a read-only retrospective analysis.
It does not rerun or replace the frozen experiment.
