# Do the boundary wire and financial prices affect retrieval?

All 15 original selected width-96 models reloaded from their sealed weight patches. The intact forward re-created all 1,415,880 archived FP32 logits bit for bit with one intra-op, OMP, MKL and OpenBLAS thread. The selected 72-way gallery models were held fixed while their boundary or price paths were intervened on. Positive changes in the table mean that the intervention increased loss. All intervals resample 16 actors while averaging the three training seeds. The cohort has previously been evaluated.

| Frozen edit | Removed path | NLL change and actor 95% interval | Intact → intervened top-1 | Fraction changing predicted label |
|---|---|---|---|---:|
| Forward ridge writes | AV boundary only | +0.00188 [−0.02240, +0.02392] | 6.53% → 6.20% | 31.93% |
| Forward ridge writes | Text boundary only | −0.06592 [−0.10567, −0.02136] | 6.53% → 5.77% | 28.76% |
| Forward ridge writes | Both boundary paths | −0.07998 [−0.12547, −0.03068] | 6.53% → 6.05% | 39.72% |
| Forward ridge writes | Equity on both sides | −0.67493 [−0.81564, −0.53097] | 6.53% → 1.22% | 99.08% |
| Same-site BP | Both boundary paths | +0.00428 [+0.00117, +0.00717] | 3.48% → 3.25% | 22.40% |
| Same-site BP | Equity on both sides | +0.14076 [+0.11100, +0.16932] | 3.48% → 1.65% | 82.02% |
| Same-site BP | Credit loss on both sides | +0.01647 [+0.01096, +0.02107] | 3.48% → 3.59% | 27.87% |

Under the original direct-write objective, removing the equity channel reduces raw NLL while driving top-1 close to chance. The joint intact raw NLL was 4.95315; the equity-removed value is 4.27821, close to the uninformative 72-class NLL of 4.27667. Under same-site BP, both equity and the boundary wire improved intact NLL in this cohort. A boundary port with a measurable effect on predictions and a port improving a specific loss answer two different questions. Price removal suppresses both recurrent feedback and the block read. Zeroing can move states outside their usual distribution. The interventions alone do not establish a biophysical mechanism or the sufficiency of the scalar message.

The accompanying per-clip float64 loss, integer prediction and mean absolute logit-change file reproduces all 35 rows including shuffled, head-only and initialized controls. Run `python verify.py` beside `per_clip.npz` and `terminal.json`. The protocol is in commit 1c652eab2ea021164e99f046ccd80524ff529fa5.
