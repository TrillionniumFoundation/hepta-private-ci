# Frozen-answer repair contract

The #5577 replay found an incorrect frozen argmax despite correct candidates in
all six diagnosed candidate sets. Those diagnostic examples are excluded from
repair fitting and tuning. This module fits only the 24 coefficients in the
ordinary/reset model's `Linear(24,1)` answer weight; the shared scalar bias
cancels in softmax and stays unchanged. Frozen embeddings are inputs, not new
encoder-training evidence.

Marginal cross-entropy includes every correct candidate. Missing correct
candidates do not produce invented targets and remain in the quality denominator.
Repeated identical states are deduplicated within a source; conflicting labels
are rejected. Source-balanced losses avoid treating repeated rows as independent
sources. A predeclared inner fitting/tuning partition must cover exactly the
original fitting sources. After all declared tuning trials, the selected setting
refits those original sources; future evaluation is a separate operation with
complete declared source coverage and the same frozen plan identity.

The prospective native plan has fit40 split32/8 and37 remaining source groups,
excluding oldtune8/calibration6/diagnostic6. Its private exact plan SHA256 is
`e602e8cc91fc26168b70a482c42ec63843872e97d1eee346b65d7e9c5231e15a`.
This separation concerns the verified original study exposure, not global model
pretraining. Four declared learning-rate/L2 trials each have1,000 fixed steps.
The native wrapper and actual run receipts follow separately.

Six NumPy protocol tests pass. They exercise source leakage, partial future
coverage, changed plans, duplicate positives/states, absent candidates, unchanged
bias and underflow-safe marginal gradients. Test embeddings are manufactured;
these tests establish no real quality or policy benefit. Every fitted artifact
stays `NoUpdate` pending independent future evaluation; prediction improvements
cannot alone establish full-cost policy benefit or production admission.
