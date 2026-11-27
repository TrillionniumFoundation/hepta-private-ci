# Adam history ablation: the frozen mechanism gate failed

After a raw-gradient interference probe failed, this distinct **FIT-only local
intervention** tested saved Adam first-moment history. All twelve trained final
states were included; none was selected by outcome. The intervention removed
only inherited first moment, retained the native updated second-moment denominator,
and matched the native full-parameter displacement norm. Each virtual step was
evaluated on a fixed different-class source, not its update source.

**Neither C-N nor E-N passed the two-seed gate. Do not adopt momentum reset
or retrain on the basis of this probe.** No model was saved or deployed.

## What actually happened

One completed child performed 12 restores, 720 forwards/objectives, 240 issued
and 240 text-component backwards, 240 native Adam virtual transitions, and 240
counterfactual generations. All virtual steps independently started from the same
respective original saved state; original parameters, moments/clocks and files
remained unchanged. Eight portable-helper tests passed before payload loading.

- **C-N:** counterfactual text wins were 10/20 in both seeds; median text gains
  and historical-displacement/text-gradient cosines were negative. Both failed.
- **E-N:** counterfactual text wins were 12/20 in both seeds and median paired
  gains were positive, but history cosines were negative (about -0.00306/-0.00335),
  opposite to the proposed adverse-history mechanism. Mean text loss was worse
  than native in both seeds, and the second seed's total loss was also worse.
- Baseline changes matter: C-N seed two's counterfactual had lower mean text
  loss than native, but **both were worse than baseline**. This is reduced harm,
  not an improvement over no update. Every cell's baseline/native/counterfactual
  values are included; S/A controls are not pooled to rescue the primary gate.

Removing history therefore did not produce consistent local cross-source benefit.
The positive E-N win counts cannot override failed direction/total-loss conditions
or mean-versus-median disagreement. No threshold, sample or step size was changed.

## Reusable package and limits

`mechanism.py` implements finite portable Adam displacement decomposition and the
frozen gate. It is a diagnostic update rule, **not a correction to Adam** and not
the private model/backprop engine. `PLAN.md` is the pre-execution design.
Run its eight handmade tests with `python -B -m unittest -v test_mechanism`.
`SUMMARY.json` contains all twelve deidentified aggregates and the resource receipt;
`VALIDATION.json` records test/engine parity scope and preparation limitations.

The sample comprises ten repeatedly reused convenience FIT sources, not 240
independent observations or held-out validation. One-step results do not identify
the cause of previous A/N quality differences or demonstrate generation benefit.
Losses are compared only within the same mode/anchor. The original experiment's
budget and quality failures remain failures. There is no equal-total-cost claim.

Complete waited child: **15.618416 CPU seconds**, 15.681578 wall seconds,
63,340 KiB peak RSS; CPU0, one numerical thread, original exclusive shared lock.
Limits: 45 CPU seconds / 120 wall seconds / 512 MiB. Tests, imports, validation,
restores, numerics and output/exit are included. Supervisor observed CPU prefix
was 0.035271104 seconds; final tail and preparation/review costs are unknown,
not zero. Guarded worker payload reads exclude DEV/TEST. A static-review search
scope lapse, which returned no matches, is separately disclosed in validation;
the worker read-scope claim does not retroactively certify preparation.

No credentials, machine paths, private inputs, per-request predictions, gradients,
model weights/moments or checkpoints are published. No scientific rerun is
authorized by this package, and no merge, deployment or CI change is included.
