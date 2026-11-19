# Historical held-out task qualification

Two additional historical task groups were selected outside the four exposed
development incidents. A separate curator retained the reference implementations,
test assertions and detailed failure output. The method developer received source
identities, counts and qualification reason classes only. No solver output was
used to choose or adjust these task gates.

The harness was frozen at 2026-10-25T13:47:14.383765Z. Its sole execution ran from
13:49:08 to 13:49:19Z, with six fixed Python subprocess calls, zero retries,
zero execution-time network requests, zero model calls and zero training.

| Group | Original implementation and original gate | Original implementation and expanded gate | Historical reference and same expanded gate |
| --- | ---: | ---: | ---: |
| H1: workspace dependency boundary | 33/33 pass | 44 methods; 36 pass, 8 fail; 13 assertion records | 44/44 pass |
| H2: Git working-source consistency | 33/33 pass | 42 methods; 34 pass, 8 fail | 42/42 pass |

All original 33 test methods still passed in both expanded runs. Every expected
method executed; there were no skips, errors or timeouts. All 22 frozen source
and runtime pins and the fixture source files were unchanged. The full controller
wall time was 11.075834 seconds; covered child CPU totalled 10.152046 seconds.

The catalogue, public results, independent raw-audit receipt and controller receipt
are retained here. Private oracle source and detailed assertion output remain
outside this public packet so the later solver evaluation can be registered
without exposing reference repairs in its method-development context.

These are **two qualified historical held-out groups**, with **zero temporal
future groups** and no solver task outcomes yet. Distinct causal families in the
same repository do not establish statistical independence. Pretraining exposure
is unknown. Original CI logs causally identifying these defects were unavailable;
the measured evidence is a counterfactual replay of genuine historical source and
regression gates. No memory-versus-retrieval or production acceptance is claimed.
