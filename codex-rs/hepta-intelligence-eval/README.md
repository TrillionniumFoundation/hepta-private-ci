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


The separate V2 operational model lease uses
`hepta-fixed-calibration-evaluator --operational-model-lease-v2 ROOT_CONFIG` and
`--inspect-operational-model-lease-v2 CONFIG CONFIG_SHA REPORT REPORT_SHA`.
Its independent E signature binds actual model generation one, the original
model/weights/training pins, physical Nomic manifest and tokenizer metadata,
normalization, an immutable CPU implementation closure and a new stable runtime
profile. It reuses explicitly declared public training-source measurements;
there is no new unseen holdout or superiority claim. Goal/request/time fields
are excluded from the model binding and forbidden in the code closure. Every
execution still needs its current Goal, seven Owners and protected FinalUse.
The sole typed purpose is `ConservativeCpuAbstentionOnlyV1`: the CPU must abstain
and fall back to the model service, never accept an answer or promote a model.

`runtime_profile` records enforced ceilings. E recomputes latency, resident and
transient allocation from original G/O numeric observations; checkpoint, write
amplification, inflight and load ceilings are not represented as measurements.
The original 4,000,000 ppm write amplification maximum and 24-hour lease cap
remain enforced. Expiry is clipped to all original source/role expiries.
The opaque reader retains verified Root-owned source FDs, so a Goal does not
rehash the physical encoder. Current admission checks original paths and exact
file identities plus the current source signatures, E role, policy and lifetime.
Its retained clock floor rejects rollback during its lifetime; the separate
FinalUse authority remains responsible for the protected cross-boot clock.

The implementation closure schema is
`hepta.cpu-neuron.implementation-closure.v2`, with `worker_host`,
`fixed_encoder_program`, `encoder_runtime`, `encoder_helper_sources` and
`numpy_sources`. Each source contains only `path` and `digest`, is physically
hashed under protected Root ancestors and remains pinned at use. The closure
SHA binds those original bytes; the runtime consumer must also match its actual
WorkerHost executable and actual configured encoder closure. Native boundary
qualification does not assert installation: a fresh same-source closure, newly
measured G/O cuts, actual E role execution and the normal CPU consumer remain
required before an installed V2 lease can be claimed. Old V1 domains and reports
are unchanged.
