# Future audio-likelihood repair: evidence identity and information sets

Status: a mathematical design for a separately registered future candidate. No likelihood, model, calibration curve, existing qualification or confirmation result is changed by this document. The current 85 confirmation writer clusters and 10 qualification writer clusters cannot become fresh confirmation for the proposed repair.

## 1. The established error

`EVIDENCE_ALIAS_AUDIT.json` proves that, under the registered source construction, all equal-digit pairs reuse one identical WAV, while the examined different-digit pairs use distinct WAV identities. This affects 4/40 ID qualification pairs and 11/170 confirmation pairs. The same deterministic decoder/normalization/CNN/argmax gives the same label for identical input bytes. Thus the true observation law for an aliased pair has diagonal support, independently of unknown classification error rates.

Let the target be \(T=(T_L,T_R)\), the two classifier labels be \(O=(O_L,O_R)\), and the already frozen single-digit likelihood be \(L(o\mid t)\). The old product table assigns

\[
P(O_L\ne O_R\mid T=(t,t))=1-\sum_o L(o\mid t)^2>0.
\]

That conflicts with the deterministic identity argument. Replacing the diagonal-target columns by single-observation diagonal support repairs this logical contradiction. It does **not** establish that the old single-digit probabilities transfer to a new population, or identify the dependence between distinct recordings of one speaker. The SHA-bound audit and its digit-wise impossible mass are the evidence; the proposed equations below are future modeling choices.

## 2. When evidence identity is known matters

Define the pre-acquisition information set \(\mathcal F_0\) as the registered public image/video tensors, task instructions, past actually delivered outputs, time/budget and actual owner state. It excludes the future WAV filenames, labels, waveforms and identity hashes. Own generated outputs may update delivery and budget state; they do not create a new independent observation of the target.

Let \(A\) indicate that the two acquired evidence instances are the same underlying registered WAV. The post-acquisition information set is

\[
\mathcal F_1=\mathcal F_0\vee\sigma(A,O,\text{actual arrival time, cost and owner transition}).
\]

The current source allocator's identity-to-target relation is a property of the acquisition protocol. Knowing that protocol before acquisition does not reveal the realized value of \(A\). Three cases must be distinguished:

| Identity access | Permitted update and planning |
| --- | --- |
| Alias status is learned only after acquisition | Plan over the joint future event \((A,O)\). Update the posterior with both observations only after they actually arrive. |
| Alias status is a legitimately available public fact at the initial decision | Condition the initial belief and future law on that fact. Do not include its likelihood a second time at arrival. All controls receive the same access and cost. |
| The policy receives only two classifier labels; alias status is never exposed | Marginalize alias status out of the observation law. Identical classifier labels alone do not prove evidence identity. |

If a future system can cheaply query identity before reading/encoding audio, that query is a separate information-acquisition action. Its admissibility, access time, cost and update must be registered. A trusted driver may know private source paths to locate files, but exposing target-bearing directory names to the policy is not an identity query.

Exact byte equality is sufficient for the present deterministic processing argument. Different SHA-256 values do not prove independent evidence: copies with different encodings, shared utterances, common speakers and common environments may still be dependent. Provenance should identify the underlying acquisition as well as the byte artifact. If preprocessing or inference is stochastic, that randomness must enter the law; diagonal label support is justified here by the fixed deterministic pipeline.

## 3. An observation space that represents alias status

Under the specifically audited mechanism, \(A=1\) exactly when \(T_L=T_R\). This implication must be checked anew if the allocation mechanism changes; it is not a universal property of speech. Let \(J_{uv}(o_L,o_R)\) be a properly specified joint label law for **distinct** recordings of the same speaker when \(T=(u,v)\), \(u\ne v\).

A useful future observation space has 110 events:

- Ten alias events \(e=(1,o)\), representing one unique observation used in both positions.
- One hundred non-alias events \(e=(0,o_L,o_R)\), including cases where distinct recordings happen to yield the same classifier label.

The structural law is

\[
\widetilde L((1,o)\mid (u,v))
=\mathbf 1_{u=v}L(o\mid u),
\]

\[
\widetilde L((0,o_L,o_R)\mid (u,v))
=\mathbf 1_{u\ne v}J_{uv}(o_L,o_R).
\]

Each target column sums to one when the supplied single and joint laws do. For a prior \(q_0(t)=P(T=t\mid\mathcal F_0)\), the arrival mass and posterior are

\[
p(e)=\sum_t q_0(t)\widetilde L(e\mid t),\qquad
q_1(t\mid e)=\frac{q_0(t)\widetilde L(e\mid t)}{p(e)}.
\]

With an alias event \((1,o)\), only diagonal targets retain support, and they receive **one** factor \(L(o\mid t)\). Squaring that factor would count one observed waveform twice. If the alias fact was already used to form \(q_0(T\mid A=1)\), update with the conditional single-observation law; do not apply \(P(A=1\mid T)\) again.

If identity is unavailable to the policy, its 100-event law instead marginalizes \(A\). Diagonal target columns put \(L(o\mid t)\) only on \((o,o)\); off-diagonal target columns use \(J_{uv}\). That repairs support without granting additional identity information. It is a different information design from exposing the 110-event identity-aware observation and must have its own frozen interface.

A computed event with zero predicted mass requires an explicit off-support response and retained diagnostic. It must not be turned into a confident posterior by silently clipping the denominator or assigning the observed target. Registered smoothing can stabilize admissible probability cells, but it should preserve known structural zeros.

## 4. Same-speaker dependence is not identified by two marginals

Even if the single-digit marginals were known exactly, they do not identify \(J_{uv}\). For instance, suppose each of two classifiers is correct with probability 0.9. The following joint tables for correctness indicators share those same marginals:

| Law | Both correct | Left only correct | Right only correct | Neither correct |
| --- | ---: | ---: | ---: | ---: |
| Independent | 0.81 | 0.09 | 0.09 | 0.01 |
| Perfectly aligned errors | 0.90 | 0.00 | 0.00 | 0.10 |
| Maximally separated errors for these marginals | 0.80 | 0.10 | 0.10 | 0.00 |

Consequently, a product likelihood chooses one coupling rather than deriving a joint law from the marginals. With \(p_L,p_R\) as marginal correctness probabilities, the joint success can lie anywhere within the Fréchet bounds

\[
\max(0,p_L+p_R-1)\le P(\text{both correct})\le\min(p_L,p_R).
\]

Speaker heterogeneity alone can create dependence. Even under conditional independence after a latent speaker characteristic \(S\),

\[
J_{uv}(o_L,o_R)
=\operatorname E_S[L_L(o_L\mid u,S)L_R(o_R\mid v,S)]
\]

need not equal the product of the two marginal expectations. Speaker selection, label coverage and the source construction can also change the mixing distribution. Existing old single-WAV accuracy and marginal calibration do not resolve this.

A new paired development panel can estimate a structured joint law or a shared-speaker random-effect model, with held-out **speakers** and a fixed observation vocabulary. Cross-validation should group every pair and recording from a speaker together. Shrinkage toward a product law is a modeling decision to preregister, not a certificate of independence. With insufficient pairs for a 100-by-100 law, the uncertainty should remain visible rather than being hidden by smoothing.

An alternative is a stated ambiguity set. For fixed marginals, each \(J_{uv}\) can belong to the transportation polytope of nonnegative matrices with the required row and column sums, plus known alias constraints. For a **fixed** future policy and fixed prior, expected exponential loss and strict success are linear in these joint probabilities, so their bounds are finite linear programs. A robust action can minimize worst-case moment while requiring worst-case terminal success above the original admission threshold. This is a potentially conservative future candidate; it may reject acquisition entirely.

That conservative computation is not automatically statistically valid: uncertain marginal probabilities require their own confidence/uncertainty set, and the true law must be justified as lying in it. Also, optimizing a policy changes its posterior-dependent action mapping. One cannot claim a minimax optimum by bounding a fixed product-policy output after the fact. Sequential local ambiguity sets can assume rectangularity that a shared latent speaker does not satisfy; either justify that assumption or preserve a coupled episode-level set.

## 5. Backup, admission and owner state

Let \(\pi(e,s')\) denote the registered H1 action after actual event \(e\) and owner transition \(s'\). A complete acquisition moment has the form

\[
M_{\rm acquire}(q_0,s)
=\sum_t q_0(t)\operatorname E_{e,c,s'\mid t,s}
\left[\exp\{-\gamma(U_{\pi(e,s'),t}-c-c_{\pi(e,s')})\}\right],
\]

with explicit rejection utility and already paid costs when no future action is feasible. If costs, evidence and resource failures are correlated, the expectation uses their joint transition. Replacing a random cost by its mean inside an exponential generally changes the objective. A deterministic unit cost is permissible as a declared model but cannot stand in for a measured stochastic resource law.

The corresponding acquisition correctness forecast is the expected **terminal strict success of the selected continuation policy**, including future refusals and failures. It is not the current draft's correctness and must not be set to one to force exploration. It needs policy-, route- and stage-aware calibration on development data and an independent qualification with the original selected-action ECE criterion. The future resource transition remains an explicit unresolved input whenever it has not been modeled; actual current owner admission masks remain authoritative.

For observed alias events, a future implementation may encode an identical waveform once and reuse the resulting observation. If the current driver encodes it twice, the cost record must still count the two operations actually performed. A deduplication change can affect cost and admission behavior, so it belongs in the next frozen candidate rather than a silent replay adjustment.

## 6. Required next registration

The next candidate should freeze the acquisition information boundary; whether alias identity is observable; the observation alphabet; single and joint law estimators; structural-zero handling; actual cost/rejection model; native ABI; stagewise policy; calibration bins and folds; and full source-role exclusions before independent data are opened. The new calibration and confirmation must exclude all sources already used for the original model selection, qualification, confirmation and this diagnosis.

The existing fixed-late control must receive the same legitimate evidence access and actual cost accounting. An identity-only ablation can separate changes in available information from changes in the probability model; a marginal-versus-paired-law ablation can address dependence, subject to a prospectively controlled comparison budget. Neither can be retroactively inserted into the completed current result.

This design closes the mathematical explanation of why duplicated evidence needs a different observation law. It leaves empirical joint-law estimation, new native execution, policy-specific calibration and new independent confirmation outstanding.

## Isolated executable interface

The future interface is implemented in [`../followup/unique_evidence.py`](../followup/unique_evidence.py), with the finite analytic verification in [`../followup/verify_unique_evidence.py`](../followup/verify_unique_evidence.py). The actual result is [`../followup/VERIFICATION.json`](../followup/VERIFICATION.json). The 285 lines across the interface, verification and package initializer are separate from all frozen execution paths.

Its ten checks cover only finite analytic support, normalization, sequential conditioning, arrival-time alias information, receipt idempotence, atomic rejection and the two coupling counterexamples. They establish neither a learned same-speaker joint law nor empirical posterior calibration. This interface has not repaired or requalified the current candidate; no current source or result was reopened for fitting it.
