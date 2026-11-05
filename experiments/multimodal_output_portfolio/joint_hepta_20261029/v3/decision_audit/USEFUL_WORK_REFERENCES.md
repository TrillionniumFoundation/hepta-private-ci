# Useful-work evidence: verified literature and scope

Checked against primary sources on 2026-11-05. This note verifies citations and
records design implications. It does not establish HEPTA effectiveness,
adoption eligibility, distributed-runtime safety, or proof-of-work security.

## 1. Latent-LoRA

**Latent-LoRA: Compact Latent-Space Adapters with Gradient-Free Routing for
Continual Learning**, Findings of EMNLP 2026, pp. 29563–29580, October 2026.
[ACL record](https://aclanthology.org/2026.findings-emnlp.1390/);
[paper](https://aclanthology.org/2026.findings-emnlp.1390.pdf).

The method fits Gaussian mixtures to pooled frozen token embeddings and uses
compact adapters in an SVD-derived weight subspace. It is a useful baseline for
testing whether a learned HEPTA router adds value. "Gradient-free routing" does
not mean that the statistical router has no estimated parameters or cost:
mixture means and shared covariance still require fitting and storage.

The paper's limitations include overlapping task distributions, cubic
covariance-inversion cost in embedding dimension, and evaluation only up to
13B parameters. Training has explicit task boundaries; streaming without such
boundaries is listed as future work. A reproduction must distinguish this
setting from task-boundary-free Cell discovery and include router fitting,
regularization, storage, and inference in its resource ledger.

## 2. ATLAS

**ATLAS: Learning to Optimally Memorize the Context at Test Time**, ICML 2026,
PMLR 306:7361–7390.
[Official proceedings](https://proceedings.mlr.press/v306/behrouz26b.html).

ATLAS addresses limited memory capacity, updates focused only on the latest
input, and restricted management of fixed-size memory. Its memory optimization
uses current and past tokens. This motivates testing bounded replay and
consolidation against recent-only updates. Its sequence-modeling evidence is
not a distributed ownership, concurrency, consensus, or useful-work proof.

## 3. Routed Continual Learning

**Routed Continual Learning**, arXiv:2610.38796v1, submitted 2026-10-28.
[Metadata](https://arxiv.org/abs/2610.38796);
[versioned full text](https://arxiv.org/html/2610.38796v1).

The architecture selects both a memory mechanism from a frozen library and an
experience cluster. The main comparisons use five matched complete rollouts;
the separate Global/Routed ReasoningBank comparison uses three. Adding routing
to this ReasoningBank adaptation gives no consistent reward gain and increases
mean **estimated API cost by 8%–29%**. This is a specific adaptation and frozen
price-schedule result, not a universal routing penalty or a complete energy,
storage, or deployment-cost estimate.

The authors freeze components before confirmatory evaluation, match actor
interfaces and permissions, and treat complete rollouts as replication units
because persistent state couples instances. They explicitly do not evaluate
simultaneous updates, stale reads, or cross-model reuse. Also, their 100K-token
history cap is per cluster in routed conditions and global in Global ICL;
this is not an equal aggregate memory-storage budget across methods.

## 4. Optimal stopping

**Optimal Stopping of Self-Refining Foundation Models**, Kim Hammar, Tansu
Alpcan, Emil C. Lupu. Accepted at CDC 2026; Imperial records acceptance on
2026-07-15. arXiv:2608.10729v1 was submitted 2026-08-11. The December conference
has not yet occurred as of this review.
[Imperial record](https://spiral.imperial.ac.uk/entities/publication/f408dcd8-e148-4d0e-b576-dc04f4375c9b);
[arXiv record](https://arxiv.org/abs/2608.10729);
[public paper](https://arxiv.org/pdf/2608.10729).

The paper compares expected improvement from another externally evaluated
refinement with its cost. Its controlled code-optimization example uses
EFFIBENCH, three models, 50 tasks, and at most ten iterations. The state retains
the best code score so far; the model uses Markov dynamics and approximately
constant per-iteration cost. These assumptions do not establish optimality for
an arbitrary Cell network or justify compensating hard constraints with high
predicted utility. STOP comparisons must preserve the actual currently
deliverable result and state their objective, units, continuation, and cost
boundary.

## 5. Verifier gaming in inductive reasoning

**LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking**,
arXiv:2604.15149v1, submitted 2026-04-16.
[Primary record](https://arxiv.org/abs/2604.15149).

The study reports instance-label enumeration passing extensional verification
without inducing the intended relational rule. Its Isomorphic Perturbation
Testing distinguishes such shortcuts from outputs invariant under logically
isomorphic tasks. This supports adding semantics-preserving perturbations to
HEPTA evaluation. It does not show that all RLVR models or tasks fail to learn.

## 6. Previously missing October citation

**Diagnosing and Correcting Reward Hacking in Verifiable Instruction
Following**, arXiv:2610.19525v1, submitted 2026-10-14.
[Primary record](https://arxiv.org/abs/2610.19525).

This is the source for the claim that increased formal constraint satisfaction
can coexist with reduced substantive response quality. The paper proposes
CALIF, adding a calibrated likelihood bonus from a frozen reference policy to
verifier rewards. The result is specific to the evaluated instruction-following
settings; neither verifier execution nor the added proxy is a certificate of
complete user or social utility.

## Project requirements derived from this review

These are HEPTA protocol requirements, not claims that the cited papers proved:

- Pin the legal history, encoder/embedding, decoder, tools, visible feedback,
  information cutoffs, and resource caps for each comparison. Report differences
  in total memory and parameter budgets rather than hiding them under matched
  per-component limits.
- Include retrieval, centroid/ridge, frozen-embedding routing, small adapters,
  equal-parameter single heads, fixed routing, and unchanged structures where
  applicable. Charge failed candidates and all selection/search work.
- Freeze candidates, critic, objective, continuation policy, cost units, and
  evaluation rules before a future confirmation window. Development bootstrap
  intervals do not become qualified action-value bounds by relabeling them.
- Count independent tasks, source clusters, or complete rollouts. Replicas of
  the same request do not increase independent sample size. Preserve pairing
  and predeclare correction for multiple candidates and repeated monitoring.
- Compare an admissible action with STOP in the same state and units. Reserve
  exploration separately under a predeclared action list and finite spend and
  attempt caps. A failed authorized experiment still consumes its budget; it
  does not earn a model-improvement reward.
- Keep service fulfillment, commissioned research, and independently qualified
  adoption as separate outcomes. None of these literature results authorizes
  increasing chainwork from service payments or local learning signals.
