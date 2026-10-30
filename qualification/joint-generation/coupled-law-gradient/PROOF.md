# Coupled-law derivative: exact smooth branches, explicit refusal boundaries

Use canonical observed-semantic coordinates after fixed transport. Let
d=min(p,q),a=p-d,b=q-d,r=sum(a)>0 and L=diag(d)+a b^T/r. For a fixed table H,
F=<L,H>=d·diag(H)+a^T H b/r. Define alpha=a/r,beta=b/r. Without changing beta's
normalization or the original denominator,

U=H beta-(alpha^T H beta)1; V=H^T alpha;
F_p=U+t*(diag(H)-U-V); F_q=V+(1-t)*(diag(H)-U-V),

where t=1[p<q] on each strict branch. These follow by differentiating with respect
to d,a,b and applying da=dp-dd,db=dq-dd. Structural zero/zero coordinates have no
raw preimage when strictly positive raw policies are pushed through valid maps.
They cannot influence the raw-policy derivative. Positive exact ties are rejected:
no classical derivative,Clarke midpoint or STE is silently selected.

S=sum(L)=sum(q),including an off-simplex unequal-mass extension when r>0. The
actual CDF-normalized additive value is F/S with H=R. With H=exp(-rho R),the CE is
-log(F/S)/rho. Derivatives of NEGATIVE utility with respect to probabilities are:

- A: -F_p/S and -F_q/S+(F/S^2)1;
- N: F_p/(rho F) and F_q/(rho F)-1/(rho S)1.

The implementation retains these normalization terms explicitly. A fixed transport
pulls derivatives back by destination gathers. The raw softmax VJP is
p_i(h_i-sum_j p_j h_j),and likewise q; divide by the original full batch size.
The unchanged aligned-anchor derivative is added separately with coefficient.2.
This chain is tested against the independently qualified actual normalized serving
law,not only against a self-implemented loss. Fixed reward/rho profile[-.35,1] and
{0,1.5} keeps the exponent bounded; no small-rho/general-utility claim is made.

When BOTH destination maps are constant,the complete composition is a deterministic
pair,even if the two semantics differ. Its value is that pair's reward and both
raw-logit gradients are exactly zero. One constant map alone does not qualify.
The original anchor/optimizer may still have roundoff or history; zero current
utility gradient is not a guarantee of zero Adam parameter movement.

At nonconstant r=0 a generic two-class matching reward has an absolute-value cusp.
Reject that point and all other positive exact min ties; one-sided boundary tests
demonstrate the lack of a unique ordinary derivative rather than claiming C1.

## Fixed numerical domain (not a precision theorem)

Require positive raw softmax outputs; no underflow support repair. On nonconstant
rows require min(rA,rB)>64*float64epsilon and
abs(rA-rB)<=sqrt(float64epsilon)*max(rA,rB). Check finite/nonnegative alpha,beta,
their sums and raw/CDF-normalized marginal errors<=1e-12. No denominator is replaced,
no epsilon is added,and beta is not renormalized. These are prospective conservative
admission restrictions,not a proof of complete gradient error<=1e-7. The relative
guard limits rB/rA mismatch; H,F and later operations still need numeric validation.

Exact dyadic residuals2^-10,2^-20,2^-40 are tested as accepted;2^-50 rejects under
the fixed floor. A separate non-dyadic/unequal-mass near-policy fixture rejects under
the relative guard. Neither threshold comes from training or validation outcomes.
Any scientific violation terminates the fixed run; there is no threshold relaxation,
masked row skipping,gradient clipping beyond the original optimizer,or rescue rerun.
