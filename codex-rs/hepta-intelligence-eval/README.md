# Independent evaluation

The product qualification ingress is `ProductEvaluationRunnerV1` with signed
qualification evidence and a durable, fenced final-holdout owner. An eligible
receipt still requires independent Selector acceptance of the exact immutable
artifact tuple. Calibration measurements never produce that receipt.

`decide_with_signed_calibration_preflight_v1` is an earlier veto over an actual
witnessed ledger cut. It verifies the original admitted Generator signature,
GoldObserver cut signature, authenticated dataset freeze, and independent
Evaluator signature. It replays the complete readonly ledger, verifies the V3
dataset against it, and derives both policy scores from terminal authenticated
outcomes. Generator, Observer and Evaluator must be pairwise independent;
the dataset producer must also be independent from the Evaluator.

The opt-in Linux binary `hepta-fixed-calibration-evaluator` executes this veto.
It runs in a bounded service as a dedicated user, with no supplementary groups,
no capabilities and `NoNewPrivileges`. Its private key is created by that user;
the provisioning administrator registers only the public key. The immutable
root-owned request pins the evaluator program, observer program, model weights,
root verification key and threshold. The program checks actual permission denial
for the original calibration gold and every other role's private key. It accepts
only a protected readonly ledger and signed custody publication, and has no
arbitrary metric or signing endpoint.

Build with `--features fixed-eval-host --bin hepta-fixed-calibration-evaluator`.
The CLI accepts `--request ROOT_OWNED_CONFIG`, or the separate initial key setup
`--initialize-key PRIVATE_KEY --uid UID --gid GID` inside its bounded service.
The `fixed-eval-host` feature also enables the ledger custody host that publishes
these exact cuts. Different credentials alone do not establish independence;
the administrator authorizes the immutable program and enforced permissions.

An unsuccessful primary comparison returns a signed `rejected` decision and
preserves deployed state. A successful calibration comparison returns
`requires_final_qualification`. Both return `qualified=false` and deny all
activation authority. The production runner still needs its preregistered plan,
fenced final holdout, actual reference outputs and costs, confidence and support,
retention and unlearning evidence, and independent Selector approval. The public
SciFact calibration review is not a secret holdout or a native automation claim.
