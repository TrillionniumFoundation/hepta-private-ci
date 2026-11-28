# An indistinguishable current boundary with active restoring and panic forces

This controlled experiment retains deterministic local financial force feedback and the original endogenous boundary, transport and reset in a 32-atom stock HCSN neuron. All 729 histories start from the same initial distribution, with six ternary inputs. Both actual signed forces remain nonzero throughout the final states on the assessed panels. We use recurrent boundary weight .55, input gain one, physical drift gain .12, and positive restoring/loss gains .4/.6. The neuron may optionally feed its previous first-passage flow into its proposed principal at gain .25.

Each history's seventh control cancels its own recurrent term and optional flow feedback. Consequently its seventh reported log boundary is exactly zero for every history. The required compensation stays within the original training-control span; across the four panels its absolute value never exceeds .184. In the zero-flow-coupling cases, we additionally give all histories the identical eighth control zero; the current emitted boundary on that common frame remains bitwise zero. The next exogenous input +.77 is identical in every case.

| Boundary path | Flow gain in principal | Minimum and maximum next flux at common current boundary | Sharp absolute-error radius |
|---|---:|---|---:|
| Step | 0 | .29574773, .41316649 | .05870938 |
| Step | .25 | .22434635, .49182152 | .13373758 |
| Linear in log boundary over the interval | 0 | .24672042, .33043762 | .04185860 |
| Linear in log boundary over the interval | .25 | .18801511, .40256314 | .10727401 |

With zero explicit flow-to-boundary feedback, all compared histories also share exactly the same next log boundary 0.17386033910513024. The difference in future flux therefore persists while the financial drift is active, even with the next boundary supplied. With flow feedback, the same exogenous input can produce different endogenous next boundaries. For the step panel, the two extremal flows above arise at next log boundaries .17404371 and .17761569. Each reported radius is exactly half the range over that finite dictionary. It only limits decoding from the current boundary, subject to the specified histories. The seventh controls may differ between histories.

[Complete controls, compensations, emitted financial channels, drifts and future messages](signed_reachable.npz) · [Forces, witnesses and numerical ranges](signed_reachable.json) · [Executable construction](signed_reachable.py) · [Memory-dependent recovery](MEMORY.md).
