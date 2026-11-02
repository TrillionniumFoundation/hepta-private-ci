# Scope of the conservative two-pool gate

At a fixed visible prefix, let r be the number of still-unemitted mandatory
outputs, b the remaining READ budget, and c=0.04. The task keeps its original
four-output normalization. Every branch's future reward lies in [-bc,r/4], so a
paired difference Y lies in [-K,K], K=r/4+bc. Both the root request and all future
light-tail READ requests are included. Past outputs and fees cancel in the paired
comparison. The implementation's integer reward is 25*correct_count-4*READ_count,
and dividing by 100 recovers the original task reward exactly.

Conditional on the prefix, frozen models, and the first pool's selected action,
the second pool compares only that fixed action with the fixed baseline action.
For n independent paired model futures, one-sided Hoeffding gives

Pr(mean(Y)-E[Y] >= K*sqrt(2*log(1/alpha)/n)) <= alpha.

Thus the declared positive-LCB rule is conservative for this model-local root
comparison. It needs no extra factor of three for the first pool's action search
because the second pool is independent of that selection. Reusing the second
pool to reselect an action, tune the threshold, or decide whether to collect more
samples would invalidate this argument. Coupling the two branches within each
sample is allowed; independence is required across the paired futures, not
between branches.

The campaign caps validation calls at G=12*11*20=2640 and uses alpha=0.05/G.
Union bounding the model-local errors gives at most 0.05 for this declared family
of tests. CRN sharing across core comparisons does not itself require independence
between tests; no core may use another core's validation outcomes to choose its
own candidate. Distinct selection/validation seeds and the 480-entry collision
check are explicit operational requirements. At the initial prefix K=1.12 and
n=512, the radius is approximately 0.230833. Frequent fallback is expected under
such a conservative fixed budget.

Service failures leave the last successful observation unchanged and still debit
the READ budget and fee. Successful delivery precedes the same-tick mandatory
output. STOP disables future READs but retains all mandatory outputs; WAIT and
READ branches continue with their own observed states and frozen light policy.
The paired branches share latent model paths and per-arrival service uniforms.
This coupling is valid because READ does not modify the physical path, and the
service process is independent of latent content. Simulated services use the
frozen fitted q; actual task execution keeps the original true declared service
law, so the confidence calculation does not eliminate service-model error.

The bound is for a fixed prefix's two root actions followed by the frozen light
tail under the declared model. It does not certify true-world dynamics or risk
calibration, unvisited prefixes, whole-task expected improvement, each realized
episode, training value, or CPU/memory/energy economics. The shared known renewal
sampler is a model prior, not learned ordinary dynamics or an actual-world oracle.

The first independent scalar check found 21/45 failing cases in an initial
vectorized head: branch state/action/READ traces matched, but roundoff in uniform
content changed argmax and reward. Its original source, receipts, and results are
retained. The revised implementation sends uniform rows through the original
scalar head using unique visible states. Same 45 cases/1080 root-sample branches
then matched integer rewards, correct counts, READ counts, and full feedback-state
trace hashes. The final guard revision was also rechecked on all 45 cases.
This preserves the original executable head's behavior rather than redefining
uniform ties to improve a result.
