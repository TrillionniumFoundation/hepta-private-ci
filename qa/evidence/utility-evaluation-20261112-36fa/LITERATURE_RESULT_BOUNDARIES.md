# Literature boundary check for utility acceptance

Checked on 2026-11-12 against the primary sources named in the user request. This note documents the boundary of the cited results; it introduces no reward, authority, evaluation contract or acceptance change. The source-pinned implementation assessment remains [UTILITY_REQUIREMENT_COVERAGE_A8C41.md](UTILITY_REQUIREMENT_COVERAGE_A8C41.md).

## Peer prediction

Qiu, Carroll and Allen, *Truthfulness Despite Weak Supervision: Evaluating and Training LLMs Using Peer Prediction*, ICLR 2026. The main-paper conclusion, printed page 9, explicitly limits its theorems to unilateral deception and leaves participant collusion outside those guarantees; Appendix B contains initial collusion experiments. Theorem 1 is a Bayesian Nash equilibrium result under the specified shared-prior setting. Empirical committee scaling and weaker-expert results do not establish coalition resistance for a deployed committee.

[Primary proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/650f33fdfaa83f432b9cfa2a2b45d663-Abstract-Conference.html) · [Primary paper](https://proceedings.iclr.cc/paper_files/paper/2026/file/650f33fdfaa83f432b9cfa2a2b45d663-Paper-Conference.pdf).

## Preference leakage

Li et al., *Preference Leakage: A Contamination Problem in LLM-as-a-judge*, arXiv:2502.01534v3, revised 4 March 2026 and marked accepted by ICLR 2026. The study examines synthetic-data generator/judge relationships involving identical models, inheritance and model family, and reports preference toward related student models. This supports checking training/data lineage rather than treating distinct key material as independence. It does not prove that every related judge is biased in every task or that unrelated models suffice for independent operational control.

[Versioned primary record](https://arxiv.org/abs/2502.01534v3) · [Primary full text](https://arxiv.org/html/2502.01534v3).

## Predictions that affect outcomes

Boeken, Zoeter and Mooij, *Conditional Forecasts and Proper Scoring Rules for Reliable and Accurate Performative Predictions*, NeurIPS 2025. The paper separates a well-posed conditional forecast from a score that elicits truthful reporting. Forecast-invariance can follow from the specified causal separation, but does not by itself make a classical score proper. The main-paper impossibility result and proposed remedies have their own assumptions, including separating forecasts or suitable unbiased divergence estimates.

[Primary proceedings](https://papers.nips.cc/paper_files/paper/2025/hash/17da6ad7f0821c9b62a9116ff9c1cf1b-Abstract-Conference.html) · [Primary paper](https://papers.nips.cc/paper_files/paper/2025/file/17da6ad7f0821c9b62a9116ff9c1cf1b-Paper-Conference.pdf).

## Engineering consequence, explicitly an inference

For Hepta, decision-before-state records, authenticated actions, actual support/propensity, and frozen or cross-fitted critics are proposed evidence controls. Their presence alone is not a theorem that the deployed feedback mechanism is incentive compatible, causally identified or collusion resistant. The objective and observation/reward authorities must remain external to the optimizing policy, and unsupported comparisons must remain Unknown or refused.

The ordinary implementation and the deployed task must separately establish the applicable source, model-lineage, operating-control, causal-support, cost and permission facts. This note does not qualify any real A/B/C run and cannot substitute for independent outcomes or a public reward contract.
