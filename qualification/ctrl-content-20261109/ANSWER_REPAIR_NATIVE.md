# Pinned native answer repair

The fitting command verifies the original collection/source closure, normalizer,
fit-record bytes, frozen base weights, its own source and the repair core before
fitting. It executes the already-verified core bytes rather than reopening that
source for import. Candidate embeddings come from the actual ordinary/reset
`public_state_step` answer-input hook, before metadata modifies public state.

Only `answer.weight` may change. Every other tensor, including scalar bias,
encoder, core, box decoder and auxiliary heads, must match bitwise. Exported
float32 selections must match the fitted head on all fitting inputs, and a cold
load must reproduce all candidate tensors. The candidate is a separate plain
Torch state dictionary; the command never installs it.

The exact private prospective plan and native request are SHA-pinned in
ANSWER_REPAIR_NATIVE_PLAN.json. The original fit40 is internally split32/8;
four fixed1,000-step settings are tuned before a40-source refit. The future37
sources and all20 old tuning/calibration/diagnostic sources stay outside fitting.
No future label file is an input to this command. A new private native directory
retains exact sources, plan, request and dispatch input before the first fitting
label opens. Existing input files and historical receipts are not overwritten.

The three local native-wrapper tests check request and runner pin refusal before
labels or output creation, and create-once preservation of an existing result.
They do not execute Torch. Native execution is reported separately, with original
failures retained. Fitting/inner-tuning quality alone cannot establish independent
future gains or complete-cost policy returns; disposition remains NoUpdate.
