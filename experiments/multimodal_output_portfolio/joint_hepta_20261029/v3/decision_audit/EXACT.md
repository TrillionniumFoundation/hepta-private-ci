# Online decision references

This is the first review stage after #4691, frozen at
`c6773fcc3fe0520f58e0d5234713d60ecf246f31`. Historical V3 experiments and failed
scientific gates remain unchanged. This stage closes only the declared finite
decision-logic reference; it does not qualify a learned multimodal controller.

## Declared experiment

Four equally likely hidden worlds, binary shared output semantics, explicit
text/image dependencies, rational action costs, a hard action budget, and
three, four or five decisions. STOP occupies a decision. Without explicit
delivery there is no quality reward. Failed and superseded attempts keep their
costs. A public policy receives only observed action/outcome history.

The primary objective is expected terminal quality minus executed action costs.
All probability/value arithmetic in that reference uses `Fraction`. The
inherited gamma-2 entropic solver is separately checked by compiling the same
public-history DAG and replaying its chosen policy against all hidden worlds.

| Problem | Horizon | Online DP | Best fixed schedule | One-sense receding control | Clairvoyant upper |
| --- | ---: | ---: | ---: | ---: | ---: |
| XOR | 3 | 0.4 | 0.4 | 0.4 | 0.9 |
| XOR | 4 | 0.4 | 0.4 | 0.4 | 0.9 |
| XOR | 5 | 0.7 | 0.7 | 0.4 | 0.9 |
| Conditional zoom | 3 | 0.4 | 0.4 | 0.4 | 0.9 |
| Conditional zoom | 4 | 0.55 | 0.55 | 0.55 | 0.9 |
| Conditional zoom | 5 | 0.7 | 0.6 | 0.7 | 0.9 |

Independent information-set policy-tree enumeration and public-policy replay
equal the online DP exactly in all six panels. The clairvoyant solves each
potential world separately before averaging and is explicitly nondeployable.
It pays the same action costs, but can avoid acquiring information it already
knows. This distinction follows information-relaxation bounds, not a claim
that an online model can access future results.

The XOR panel identifies complementary information and non-myopic planning.
It deliberately retains the tie with an optimal fixed sensing schedule.
Conditional zoom identifies allocation after observing difficulty: an easy
case skips zoom, while a hard case acquires it. Fixed schedules may adapt
generated content to acquired observations, but cannot adapt their schedule.
The one-sense control optimizes legal output completion after one acquisition;
it is stronger than an immediate-reward rule that ignores delivery dependencies.

An independent review found and fixed a baseline bug: an infeasible unselected
content choice incorrectly rejected the whole fixed schedule. The regression
retains all positive-probability branches of a selected choice while allowing
other feasible content choices. No failed branch is silently discarded.
Probe names cannot alias the text/image action kinds; this prevents a fixed
schedule from silently switching between sensing and generation after observing.

## Reproduce

From the repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_exact -v
python -O -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_exact -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.exact
```

`evidence/EXACT.json` retains every panel, enumeration count, fixed schedule,
independent gamma-2 replay error and solver CPU/wall measurements. Solver
overhead is separate from mathematical environment values. Maximum CE replay
error in this run is approximately 1.12e-16. Both Python modes pass 14 tests.

Only a finite known model with at most five stages is established. Fresh data,
unknown transition identification, real generators, learned policy superiority,
four-arm training interaction and production cost remain separate gates.
The partial authoring checkout has no production `codex-rs` workspace or `just`;
repository-wide formatting/native qualification is not inferred from these tests.

## Primary references

- Brown, Smith and Sun, [Information Relaxations and Duality in Stochastic Dynamic Programs](https://people.duke.edu/~psun/bio/Information_Relaxations_and%20Duality_in_Stochastic_DPs.pdf).
- Hay et al., [Selecting Computations: Theory and Applications](https://people.eecs.berkeley.edu/~russell/papers/uai12-meta.pdf).
