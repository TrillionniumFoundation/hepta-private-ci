# Fixed-basis semigroup diagnostic — P1 HOLD

This is **new read-only numerical evidence**, not a repair of the projected flow or an acceptance decision. Parent HCSN evidence candidate [#6075](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6075), exact source head `1ffcea22cf080290849b0a195888fa958e569993`. The operator and grid Git blobs are pinned in [RESULT.json](RESULT.json).

For the same 25-state fixed uniform active/refractory grid, construct `Q(dt)`, compare two repeated steps `Q(dt) @ Q(dt)` to one longer step `Q(2*dt)`, and compute rowwise total variation. The fixed Gauss rule, continuous reset, physical sigma 0.35, drifts -0.4/0/+0.4, positive gaps .001/.02 and discount .08 are declared in the report.

At zero drift and gap .001, max row TV is **0.023689623092389506**; at gap .02 it is **0.09262459023061453**. In six drift/gap combinations it ranges from **0.0236750 to 0.1084839**, although composed row-mass discrepancies remain below `6e-16`. This illustrates why perfect mass conservation does **not** prove time-step consistency, nor continuum-value accuracy.

The deliberately false exact-semigroup null was rejected in durable desktop job `1a1cd69b5ae-2564-12a5` (exit 1, retained as expected RED). The original six-regime diagnostic and two tests in `1a1cd68fdb4-2564-12a3` passed. The exact **published Git blob** `6214bdccec05ddb793fbb8e193e4b0b55d1b3329` was fetched from GitHub and sent unchanged through the process stdin to the pinned Python/Torch runtime, with **2/2 native tests PASS, exit 0**, job `1a1cd6b4dda-2564-12ae`. Raw complete stdout/stderr are preserved in [NATIVE-RAW.log](NATIVE-RAW.log).

**Scope:** synthetic fixed grid and parameters only; this does not reproduce the 14,336 recorded trained posterior comparisons of #6073, and its row difference is not their value discrepancy or task loss. The #6073 training-domain continuation audit already found **14,336/14,336** recorded positions above its unchanged 1% value threshold, so P1 remains **HOLD**. A suitable generator, within-bin moment/shape, or near-boundary/reset representation needs controlled study, then full fixed-threshold cross-regime and actual recorded-state requalification. Do not substitute an analytic value readout for a validated probability/content transport. No original C2 execution was started or altered; P0/P2–P5 remain HOLD_NO_GO.

The repository's `hcsn-boundary-audit.yml` discovers `test_*.py` and should test the newly committed module on its own exact source head. Native local GREEN is **not** an assertion of hosted CI success.
