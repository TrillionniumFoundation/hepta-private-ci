# Regenerative task-value boundary: finite evidence-cell qualification

This package defines a new, explicitly separate exponential-deadline task. It
does not replace the earlier fixed-tick task or modify its frozen evidence. The
stopping region is part of the actual task: entering FIRE submits a decoded
answer, earns its eventual correctness reward, resets the evidence state, and
starts recovery before a second job. There is no auxiliary latent feature that
the value function can ignore while the implementation calls it a normative
boundary.

The implementation is a small exact planning and execution reference. It is not
an amortized neural policy, a new production neuron, a Brownian first-passage
model, or evidence of an independent analytic-cell task advantage. An ordinary
gate with the same policy and causal inputs has exactly the same task behavior.
That null is an explicit confirmation requirement.

## One process for training, value, boundary and execution

The active state is `(job, shared_reads_remaining, signed_evidence)`, written
\(s=(j,b,m)\). Each job has an independent hidden binary label, initially fair.
At a completed READ the actual frozen content decoder returns a binary
observation. The known channel reliability is \(q_j\), so

\[
p_j(m)=\Pr(Y_j=1\mid m)
 =\frac{1}{1+\exp[-m\log(q_j/(1-q_j))]},\qquad
P_j^+(m)=p_j(m)q_j+[1-p_j(m)](1-q_j).
\]

READ waits for an availability clock of rate \(\lambda_j\). On arrival it opens
the next actual packet, runs the frozen model, pays \(c_{q,j}\), reduces the
shared budget by one and increments \(m\) by the observed sign. A deadline can
censor the wait before the packet is opened; that case pays elapsed-time cost
but no completed-READ charge. The model therefore represents waiting for
availability followed by a read, rather than paying for a remote request at
dispatch.

FIRE predicts one when \(m\geq0\), otherwise zero. Correct and incorrect
submissions receive +1 and -1; every submission pays \(c_f\). The common public
guard permits FIRE only when \(\max(p_j,1-p_j)\geq0.75\). After a nonfinal FIRE,
the evidence resets to zero and the owner completes \(k\) independent recovery
phases, each with rate \(\gamma\), before the next job. Budget is shared across
jobs. STOP abandons the remaining work. Time cost is \(c_t\) per unit of sampled
task time during READ waits and recovery.

There is **one hidden deadline sampled per episode**, with rate \(\delta\).
The owner accumulates elapsed time through every READ and recovery phase and
compares it with this same absolute deadline. It does not sample an unrelated
deadline after an action. Survival of the exponential deadline makes remaining
time memoryless, so `(job, b, m)` is sufficient for control. This reduction
would not apply unchanged to a known fixed deadline or a nonmemoryless hazard.

The sampled task clock is charged but not implemented by sleeping. Measured CPU
and wall time are additional recorded resources. They are not the sampled
deadline, physical energy, or demonstrated hardware savings.

## Regenerative Bellman/QVI operator

Set \(\beta=\gamma/(\gamma+\delta)\). The integrated recovery operator for a
nonfinal job is

\[
\mathcal R V(j,b)=\beta^k V(j+1,b,0)
 -\frac{c_t}{\gamma+\delta}\sum_{\ell=0}^{k-1}\beta^\ell.
\]

The three action values at an active state are

\[
\begin{aligned}
Q_{\rm STOP}(s)&=0,\\
Q_{\rm READ}(s)&=
 \frac{\lambda_j\{P_j^+(m)V(j,b-1,m+1)
 +(1-P_j^+(m))V(j,b-1,m-1)-c_{q,j}\}-c_t}
 {\lambda_j+\delta},\\
Q_{\rm FIRE}(s)&=|2p_j(m)-1|-c_f+\mathcal R V(j,b).
\end{aligned}
\]

The final job has no recovery or continuation after FIRE. READ is unavailable
at zero budget; FIRE is unavailable when the shared confidence guard fails.
The finite QVI is \(V(s)=\max_{a\text{ legal}}Q_a(s)\). Entry into its FIRE
region is the cell's consequential first event. All fixed, directly fitted and
value-derived regions use this same process and guard.

States are topologically ordered: a READ reduces budget and a FIRE advances
the job. Exact backwards substitution solves the finite problem. A separately
constructed linear program minimizes the sum of values subject to all Bellman
inequalities; it does not import the model's reward or transition arrays.

The rectangular envelope has `jobs * (B + 1)^2` states. Not all envelope states
are reachable from the declared start. Every fitted hard policy records the
full per-state value, Bellman residual and gap as well as separate maxima over:

- The entire finite envelope.
- States reachable under some legal policy.
- States reachable under the deployed hard policy.
- The initial state.

An initial gap of zero alone is not reported as all-state optimality.

## Actual decoder observation contract

`PayloadBank` creates exactly eight fixed `symbols`/`dt` inputs and runs the
real frozen 6,217-parameter FullHX model on every one. It groups these inputs by
their **observed decoded class**. The episode generator first samples a desired
observation through the declared binary channel and then chooses an input from
the corresponding verified class. It does not assume that an intended symbol
always survives the decoder.

Every actual READ opens a unique packet file and runs the model. A second,
counted read checks that the same bytes were inferred and that model inputs
belong to the verified support. Packet nonces distinguish bytes while being
irrelevant to the decoder. The owner rejects inputs outside this contract or
changed decoded classes. Labels remain in a separate evaluator file and are
accessed only after that execution is terminal.

Thus the declared observation law is exact on this finite, exhaustively
verified input support, conditional on the frozen decoder behaving identically.
This does not test natural language, arbitrary content, decoder robustness
outside the support, or an unknown learned observation channel. The source,
checkpoint and upstream manifest hashes are part of preparation.

## First-event propagation and gradients

For a fixed hard or randomized stopping table, `first_fire_policy` builds the
killed continuous-time generator over READ states. At a packet arrival,
observation probabilities and the next state's policy split probability mass
between continued READ, FIRE absorption and STOP killing. Deadline hazard also
kills mass. A block matrix exponential produces the first-FIRE CDF and density.

A randomized policy can FIRE immediately, so the initial atom is recorded
separately. `at_risk` is probability still alive and continuing, not `1 - CDF`:
STOP and deadline censoring also remove mass. This operator describes the next
FIRE from the supplied active state; it is not the CDF of every later FIRE.
Later jobs and recovery are included in the regenerative value operator and in
actual execution.

The Frechet derivative differentiates the finite matrix exponential with
respect to arrival-rate and deadline-rate directions **holding the policy
table fixed**. It does not differentiate policy membership, guard changes or
the optimizer's response to a changed contract. A hard finite stopping set is
piecewise constant and changes nonsmoothly; no smooth-pasting derivative is
claimed.

For randomized tabular logits, the exact total-return derivative is

\[
\frac{\partial J}{\partial z_{s,a}}
 = d^\pi(s)\pi(a\mid s)[Q^\pi(s,a)-V^\pi(s)],
\]

where the occupation weight includes all preceding survival, actions, resets
and recovery. Directional finite differences check this full continuation
gradient. Ground-truth Monte Carlo independently samples labels, clocks and
observations to check total value and first-event distributions.

The final fitting method is 600 fixed mirror updates of all legal action
logits, using the **current policy's** action advantages. It uses the known
model, includes counterfactual states and fits one public contract at a time.
It is model-based policy improvement, not supervision by optimal-Q labels and
not model-free gradient learning. Every step's objective, loss and full
objective gradient are preserved. The original Adam development attempt and
its suboptimal hard outcomes are retained in the evidence archives.

Soft return, hard argmax return, their difference, all-state residuals and the
final soft gradient are reported separately. Hard deployment can be exact
while the soft gradient remains above the declared numerical tolerance; that
does not certify soft optimizer convergence.

## Prepared confirmation design

`campaign.py prepare` writes protocol, 40 complete fits, fixed and QVI policies,
independent LP references, full certificates, timing, source copies and a
freeze manifest. It creates **zero confirmation episodes**. The separate
`confirm` command requires the exact preparation digest and the parent's
immutable remote freeze reference before creating episodes.

The protocol fixes four nominal and four stress contracts, five fit seeds,
600 mirror updates, fixed evidence threshold two and 128 distinct episodes
per contract-fit. Each episode is executed by five policies: fixed analytic,
direct hard analytic, direct soft analytic, QVI analytic and QVI ordinary.
There are 5,120 episodes and 25,600 rollouts. The execution order is separately
shuffled; all five policies share each episode's packet and clock bytes. Each
contract-fit has a distinct episode seed range.

The primary paired effects are direct hard minus fixed and QVI minus fixed.
Hard minus soft is a secondary deployment-gap comparison. QVI analytic versus
ordinary must be a pathwise task null, including observations, submissions,
costs and censoring. Analytic execution additionally computes the first-event
distribution at each decision, and its measured overhead remains in costs.

The declared primary CPU accounting scenario prices one CPU second at one task
utility unit and amortizes policy preparation across 1,000 deployment sessions.
Sensitivity scenarios cross CPU prices `{0, 0.1, 1, 10}` with deployment volumes
`{128, 1000, 10000}`. For a paired policy comparison the reported net difference
is `delta_task_utility - kappa * (delta_execution_cpu + delta_preparation_cpu/H)`.
Enclosing execution CPU already includes CDF, decoder and owner work. Common
episode generation, decoder/support setup and common verification are recorded
and cancel in these matched alternative-policy contrasts; component timers are
not added a second time. Fitting and additional certificates are fully charged
to either direct-policy deployment alternative. Fixed and QVI alternatives
pay their own model construction, policy construction/solving and certificates.
Each deployable policy table is actually serialized, hashed, reloaded and
validated in preparation. Confirmation loads each alternative's own artifact
and measures that load again. These costs enter its amortized preparation
charge. Both direct-policy artifact exports are charged to either alternative,
because the declared fitting pipeline emits both soft and hard policies.

Outer stage receipts additionally cover loading the complete experiment bundle,
source validation, source copies, raw-result serialization and evidence hashing.
Those experiment packaging costs are kept distinct from the per-policy
deployment charge. The outer timer ends before its own small receipt and final
manifest are written; it is not a measurement of process startup or shutdown.

Quality reports include correct submissions divided by two jobs, incorrect
submissions divided by two, completion fraction, and accuracy conditional on a
submission. A lower error count obtained by submitting less is visible in those
joint metrics. The shared confidence guard does not by itself establish a
quality noninferiority result.

Per-contract reports include conditional paired-episode intervals and a
separate five-fit cluster interval. The aggregate weights the eight declared
contracts equally and uses within-stratum uncertainty. These are unadjusted
descriptive 95% intervals for two declared primary effects, not a claim about
a sampled population of future contracts. Stress contracts are public
parameter scenarios that are replanned, not OOD generalization of one trained
model. A predeclared low-reliability/high-cost STOP control remains in all
reports.

Fixed gates, model-based fitting and exact QVI use different preparation work.
The study measures their actual work rather than calling it equal training
FLOPs. Setup, finite-support verification, episode generation, fitting,
reference solving, CDF evaluation, decoder inference, support validation and
enclosing execution times are recorded. Component times overlap enclosing
times and must not be added twice. Preparation includes diagnostic certificate
work, which is retained separately from policy execution. Any monetary or
energy conversion and deployment amortization must declare its rates and
deployment volume; none is inferred from event sparsity.

Every failed execution is retained. Captureable action failures preserve
partial real receipts and costs. A failure invalidates execution qualification
and is not silently retried or removed. `qualified` means consistency and
execution qualification only. It does not mean positive task benefit or
production enrollment; both architecture-gain and automatic-enrollment claims
remain false in the report.

## API and reproduction

The action numbering is specific to this package:
`STOP = 0`, `READ = 1`, `FIRE = 2`. It differs from the old four-action owner.

```python
from tools.hcsn.value_boundary_v2_20261031.model import Contract, Model
from tools.hcsn.value_boundary_v2_20261031.learn import fit_region
from tools.hcsn.value_boundary_v2_20261031.owner import PayloadBank, execute

contract = Contract(reliability=(.80, .86), arrival_rate=(2., 2.5),
                    query_cost=(.03, .04), deadline_rate=.10,
                    minimum_confidence=.75)
model = Model(contract)
fit = fit_region(contract, seed=74031, updates=600, optimizer="mirror")
hard = model.deterministic(fit["hard_actions"])
hard_value = model.solve(hard)["initial_value"]
first_event = model.first_fire(fit["hard_actions"], (0, contract.budget, 0), 1.)
# make_episode creates real files; use development-only destinations before freeze.
bank = PayloadBank("/tmp/my-development-support")
episode = bank.make_episode("/tmp/my-development-episodes", contract, "dev_0", 1234)
hard_run = execute(episode, contract, bank, actions=fit["hard_actions"],
                   mode="analytic_boundary", capture_failure=True)
soft_run = execute(episode, contract, bank, probabilities=fit["probabilities"],
                   rng_seed=2345, mode="analytic_boundary", capture_failure=True)
```

Run commands from the repository root with the existing NumPy/SciPy environment:

```bash
env PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m tools.hcsn.value_boundary_v2_20261031.qualification \
  --out /tmp/new-value-boundary-development

env PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m tools.hcsn.value_boundary_v2_20261031.campaign prepare \
  --out tools/hcsn/value_boundary_v2_20261031/prepared
```

Confirmation is intentionally a separate invocation after the parent has
published and verified the frozen source and preparation. The parent supplies
`--prepared`, a new `--out`, `--freeze-sha256` and `--freeze-reference` to
`campaign confirm`. No confirmation cohort is created by qualification or
preparation.
