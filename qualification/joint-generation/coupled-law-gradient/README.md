# Coupled-law gradients qualified; scientific run stopped at its numerical boundary

The smooth-branch derivative passed nine literal tests,including complete raw-logit
finite differences against the actual coupled serving law. The subsequent fixed
scientific comparison **aborted on its predeclared numerical-domain guard before
validation**. No generation-quality result or NDU benefit was evaluated.

## Qualified derivative, not a hidden STE

`coupled_gradient.py` differentiates the CDF-normalized maximal-semantic coupling
objective,including its normalization term and the full transport/softmax chain.
The fixed profile accepts rewards in[-.35,1] andrho0/1.5. The existing aligned anchor
is added unchanged. `PROOF.md` gives the branch derivatives and domain boundaries.

Both constant transport maps yield a deterministic pair andexact zero utility
gradient. Other positive exact min ties reject: no ordinary derivative or hidden
Clarke choice is invented. Raw policies must be strictly positive; residual floor
64float64eps andrelative-balance tolerance sqrt(eps) are fixed engineering rejection
criteria,not epsilon terms in the objective or a global precision theorem. The
original denominator,beta andCDF normalization are never repaired or substituted.

Stage1 actual results,0model restores/updates/data rows:

- Nine tests passed;complete anchor+utility FD maximum absolute error**8.71e-11**.
- Actual coupled-service value maximum error**1.67e-16**.
- Tie fixtures had opposite one-sided derivatives,approximately+1/−1,andrejected.
- Exact dyadic residuals through2^-40 had finite gradients;2^-50 rejected as planned.
- Constants,one-constant maps,relative imbalance,permuted semantics,swap,translation
  andinput/mode rejection were covered. Tiny-residual finiteness is not a uniform
  near-boundary gradient-accuracy guarantee.

## Actual scientific terminal state: not evaluated

The planned eight cells were independent/coupled training xA/N xseeds11/23,with the
original300updates/batch64/lr.003/anchor.2/rho1.5 andsame coupled serving evaluation.
Every arm computed both new derivatives to charge their cost equally. Four old A/N
control digests andeight finalstates were required before any validation generation.

Seed11 independent-additive completed300updates andpassed its exact old-control
digest assertion. After117updates of seed11 independent-NDU,the next batch's shared
auxiliary coupled-A call raised**relative residual mass imbalance**. This was
zero-based pre-update step117,total417completed updates. No coupled-trained model
had yet completed;the new derivative was being evaluated as shared control work.

Actual partial inventory:835auxiliary call attempts,834completed;1253forward batches/
80192rows;1base restore,2clones,1decoder observation/12images. Validation-serving
counts were all0. Neither the eight-model freeze barrier nor RESULT existed.
The original thresholds were not relaxed;no rows were masked andno rescue rerun
followed. Failed residual magnitudes were not saved,so the precise numerical cause
cannot be quantified from this record alone.

This shows the declared numerical profile did not cover the fixed FIT trajectory.
It does **not** show that coupled-law alignment worsened generation,andit does not
invalidate the earlier forward-only coupling/batch qualifications. The scientific
primary gate is**not evaluated**,not relabeled as a quality pass or a quality fail.

## Reproduction and cost

Run the literal fixtures with already qualified repository helpers:

```sh
PYTHONPATH=../explicit-semantic-transport:../semantic-coupling:../semantic-coupling-batch:../transport-aligned-training:.. python -B -m unittest -v test_gradient
```

Stage1 whole waited child:**0.568155CPU seconds**,0.589855wall,28356KiB RSS,under
5CPU/30wall limits. Stopped Stage2 whole child:**2.117035CPU seconds**,2.141363wall,
42244KiB RSS,under20CPU/90wall limits. Both were single-thread/CPU0,512MiB/4MiB,
under the existing synthetic shared lock,andfully waited. Stage2 repeated the same
nine tests before model access;that cost is included. The reused seed11 base had a
prior measured preparation prefix of0.219982CPU seconds;seed23 was not restored.
Historical base preparation,
source/review and supervisor tails remain additional,not zero.

`PLAN.md` preceded qualification;`RUN_PLAN.md` bound Stage2 without changing its
scientific criteria. `SUMMARY.json` retains qualification measurements,the complete
failure counters/progress andboth resource receipts. No model payloads,private
paths,per-request outputs or original digit-study recovery claims are published.
