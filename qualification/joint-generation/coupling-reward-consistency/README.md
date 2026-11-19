# Class-credit consistency: a verified incentive, then a fixed repair control

Under the original reward, a correct text paired with a wrong image receives class
credit.3−.35=−.05, while consistent-both-wrong receives0. With a legal command having
two remaining semantic destinations andtextcorrectness p>imagecorrectness q,
maximal coupling moves mass from consistent-both-wrong to that contradiction when
p increases. Its additive reward derivative is exactly−.05; its entropic derivative
is also negative. This is a property of the objective, not a gradient sign bug.
`PROOF.md` states the branch calculation andits limits.

A fixed payload-free test used six(P,Q) pairs, three imagequality pairs andrisks0/1.5:
36configurations, no models ordata. All18leading-text cases had negative coupled
text derivatives (−.05 foradditive, down to−.09450 forNDU); all36independent-product
text derivatives were positive **on this fixed grid**, not asserted universally.
Actual CDF-law finite differences matched within8.50e-11.

The proposed repair is the **least pointwise upward class-credit correction**:

`R_repair = R_original + (.35 - .3) * XOR(correct_text, correct_image)`.

The amount follows from the original coefficients, not a validation sweep. It raises
only the single-correct classcredit to0, preserves bothwrong/bothcorrect credit and
all imagequality terms, andrequires explicit reward mode. The helper verifies the
original fixed classcredit plus image-only quality structure anddoes not mutate it.
The repaired leading-text derivative becomes0 (maximum absolute residue1.39e-17),
not a proven positive learning signal. It guarantees classcredit monotonicity under
correction, not totalreward monotonicity if correcting an image worsens pixelquality.
This is a changed training objective, not unchanged originalNDU.

Four literal tests passed in0.374525CPU seconds,0.386781wall,28196KiB RSS, under5CPU/
30wall/512MiB/4MiB with CPU0/single-thread/existing synthetic lock andcompletewait4.
Zero model restores,trainingupdates or dataset rows. The proof doesnot establish
that this incentive caused the earlier trained-model negative result.

From this directory with existing qualified repository helpers:

```sh
PYTHONPATH=../coupled-simplex-longdouble:../coupled-prefix-numerics:../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../transport-aligned-training:.. python -B -m unittest -v test_incentive
```

The qualification plan andseparate fixed scientific RUN_PLAN retain originalreward
baselines andthe originalfiveacceptance gates. Only portable code, literal fixtures,
proof, plans andaggregates are public, not weights,private paths orper-request data.

## Fixed repair-training result: primary failed

All eight cells completed300updates; four original-reward controls exactly matched
prior independentN andcoupledN final digests. Every arm computed allfour coupled
original/repaired A/N derivatives perbatch. Both original numerical andnew incentive
literal suites (16tests total) ran before models. All8finals preceded validation.
**Every reported quality score below uses the ORIGINAL reward and original gates.**

Partial-command full/low macro contrasts,seed11 / seed23:

| Contrast | Original joint CE change | Text mass change | Greedy text change | Joint success change | Pixel MSE change |
|---|---:|---:|---:|---:|---:|
| repaired N minus original independent N | −0.007236 / −0.009075 | −0.003885 / −0.007582 | +0.001603 / 0 | −0.004778 / −0.006574 | +0.000138 / +0.000193 |
| repaired N minus original coupled N | +0.000193 / +0.000108 | −0.000071 / +0.000378 | +0.001603 / +0.001603 | +0.000099 / −0.000017 | −0.000008 / −0.000004 |
| repaired N minus repaired A | +0.010564 / +0.012628 | +0.007666 / +0.008346 | +0.008013 / +0.003205 | +0.008056 / +0.009483 | −0.000240 / −0.000267 |

RepairN−repairA passes allfive gates inbothseeds. But repairN still loses to the
stronger originalindependentN baseline, while repairN−originalcoupledN CE gains
are below.005 andtextmass/jointsuccess have small regressions inone seed each.
The **overall primary isfalse**. Correcting the proven incentive did not recover the
performance gap. This doesnot disprove the algebra, but it doesnot establish that
incentive as the main cause of the trained-model negative result. No coefficient
sweep,gate relaxation orrelabeling internalN>A as overall success followed.

Whole new science child: **17.463560CPU seconds**,17.526895wall,53248KiB RSS,
under30CPU/90wall/512MiB/4MiB,CPU0/single-thread/existing shared lock andcompletewait4.
2400updates,7220forwards/471120rows,9600gradientcalls/614400rows,2read-only repaired
reward tables/3456entries,10320served jointtables,20640CDFchecks,20scalarreference
checks and10profile roundtrips. Zero domain exceptions/failure diagnostics. Per-arm
training ranged1.874300–2.110348CPU seconds; common plannedwork isnot identicalspend.

The0.374525mechanism and0.782639numeric qualifications,11.247789prior comparison,
0.714013fixed-prefix diagnosis,2.117035old numerical abort,0.568155old qualification,
and0.447929sum of measured base-preparation prefixes are separate historical costs,
not omitted or double-counted inside this child. Source/review,olderresearch and
unknown supervisor tails remain additional. Two existing supervised base bundles
were restored; no new checkpoints were saved. NoTEST was used. Validation was
reused exploratory synthetic RGB,not fresh heldout/natural-image/original-digit data.
