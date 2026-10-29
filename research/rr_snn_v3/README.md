# RR-SNN v3: executable research reference

The bounded reference now has analytic interval primitives, physical marked spikes,
resource-aware deadlines, a trainable delayed recurrent network, complete-state
replay, and actual Linux process-crash evidence. **Hepta qualification is not passed.**

The latest [Node execution](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40868845250)
completed all eleven entrypoints at source commit
1b1351fb37b8f6db1ee5684ca6e5cfb284539c9e. The nineteen executable source files
match the retained receipt. The frozen fitted model improved heldout path
likelihood, but independent free generation revealed lower pulse counts than
its synthetic generating model. That discrepancy is retained.

Start with [the full Chinese report](REPORT.zh-CN.md),
[acceptance status](evidence/acceptance_status.json), and
[the actual Node receipt](evidence/node_receipt_40868845250.json).

## Components and evidence

| Component | Guide | Executed evidence |
| --- | --- | --- |
| Finite discounted continuation and joint deadline decisions | [Continuation](CONTINUATION.md) | 26 grouped checks |
| Constant-coefficient Brownian first passage and killed law | [Brownian](BROWNIAN.md) | 20 grouped checks, numerical domain guards |
| Physical marked spikes, refractory, resources and input events | [Events](EVENTS.md) | 22 grouped checks |
| Finite CTMC derivatives and complete-path censoring | [Gradients](GRADIENTS.md) | 13 grouped checks; fixed fit plus separate holdout |
| Two-neuron actual delayed recurrence and path learning | [Network](NETWORK.md) | 13 checks; 128 train / 128 heldout episodes |
| Fixed-input single-neuron joint replay | [Replay](REPLAY.md) | 6 restores, 4 reference faults, 32 negative cases; 4 actual process crashes |
| Dynamic recurrent-network joint replay | [Network replay](NETWORK_REPLAY.md) | 7 restores, 4 reference faults, 35 negative cases; 4 actual process crashes |
| Frozen independent free generation | [Generation diagnostic](NETWORK_CALIBRATION.md) | 2048 trajectories; all resource invariants; observed underfiring |

The original continuation-only README is preserved as CONTINUATION.md for the
history of that component. Its earlier stage status does not describe the
integrated work recorded here.

## Reproduce

Node 22 is sufficient; the process-crash harnesses require Linux. No npm package
installation is needed. From the repository root:

~~~sh
node research/rr_snn_v3/verify_node.cjs
~~~

The verifier executes all validation entrypoints, the fixed learning diagnostic
and the frozen generation diagnostic. It saves command stdout/stderr and a source
identity receipt under verification-output unless RR_RESULTS_DIR is provided.
The generation diagnostic consumes the checked-in exact fitted artifact; it does
not replace its frozen weights with a new runtime's numerically regenerated fit.
Reproduction does not increase the statistical sample size.

The workflow targets only the isolated research verification branch, uses hosted
Ubuntu, and supplies no production owner or activation authority.

## Primary results and limits

Heldout complete two-neuron path NLL decreases from 3.56909 to 3.00677.
The paired difference is -0.56232, with the fixed bootstrap interval
[-0.76552,-0.35743], conditional on this one fit. Absolute NLL includes the
fixed up channel and heldout likelihood excludes training regularization.

On fresh synthetic generation, the fitted model emits 0.12402 fewer pulses per
episode, interval [-0.15332,-0.09375]. All four strata show the same direction.
Larger remaining model budget is not a demonstrated future-utility benefit.
Full calibration acceptance is not assigned.

The trained network is a finite marked model with a declared continuation proxy.
The Brownian module is a separate constant-coefficient interval primitive, with
numerically evaluated inverses and integrals. A general endogenous moving-boundary
network solution and architectural novelty are not claimed.

The new candidate has no completed matched terminal-utility architecture comparison,
real future-window evidence, production owner receipt, or real 64/256/1024/4096
Cell measurements. Earlier V2 negative results remain relevant and unchanged.
Cell counts must not be replaced by neuron counts or policy-row counts.

## Source and output provenance

- [Network protocol freeze](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/16ecf52b7faaa43e9ab0612cc22b5dd35345f063)
  precedes first training and heldout generation.
- [Generation protocol freeze](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c391e8b7d8ceada0765b6b9d454d2736b98e04dc)
  precedes the fresh generation paths.
- [Final source identities](evidence/source_identity_check_final.json) bind nineteen
  executable files to the successful Node run.
- [Raw CI artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40868845250/artifacts/12894478078)
  has SHA-256 9454f4435d55951579712346b7d6e3ca82fc75774eccc3cc7b44a08d136f30c1
  and expires 2026-11-12. Permanent source, reference results, episode audits,
  actual process results and execution receipts are retained in this branch.

All research PRs remain separate bounded review units; see the report for links.
