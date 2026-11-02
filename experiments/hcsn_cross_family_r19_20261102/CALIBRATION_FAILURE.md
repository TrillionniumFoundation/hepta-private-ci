# Locked calibration failure, before opening confirmation worlds

Both candidate policies failed the original 10% fractional-answer error cap in
at least one declared trained family. IID failed all four fixed thresholds;
sticky and rotor passed at .9 and above. No family-specific runtime threshold or
weaker pooled gate replaced that result. Both global policies therefore froze
the declared near-concentrated fallback, with calibration_gate_passed=false.

For the class mixture at threshold .9:

| Family | Fractional accepted | Errors | Simultaneous risk upper | Gate |
| --- | ---: | ---: | ---: | --- |
| IID | 531 | 43 | 12.38% | Failed |
| Sticky | 960 | 15 | 3.22% | Passed |
| Rotor | 354 | 12 | 7.46% | Passed |

IID mixture upper bounds over .8/.9/.95/.975 were
13.68% / 12.38% / 12.50% / 13.14%. The static reference also failed IID at every
threshold. All eight global candidates and all family slices remain recorded.
A positive average across families cannot repair this failure.

The complete preparation child used102.956330CPU seconds,131.270276wall seconds
and peakRSS97540KiB. That includes fitting, public validation, OOD calibration,
all98304risk-calibration decisions, failures/refusals and output. Development and
independent audit costs are separate.

At the time this note was written, the five-family confirmation had not opened.
Source and fitted-control identities remain pinned. A later candidate must use a
new source/protocol freeze and fresh verification; no R19 threshold repair is
allowed after outcomes. A possible future mechanism experiment is to learn
class priors from masked public-stream prediction rather than complete-stream
likelihood. This is a proposed mechanism, not a tested remedy.
