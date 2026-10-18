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

Generation one is the currently qualified conservative bootstrap purpose, not
an architectural limit on future candidate generations. A new candidate still
enters through the existing independent paired E result, Selector and Artifact
CURRENT owner; this lease cannot replace that qualification or widen its claim.

The custody binary additionally accepts `--prepare-climate ROOT_CONFIG` and
`--inspect-climate ROOT_CONFIG` for the pinned official Climate-FEVER bank.
`tools/hepta_prepare_climate_holdout_features.py` first freezes a complete
feature-only component manifest under Root custody. It reuses the previously
frozen public and historical feature comparisons, excludes the entire public
example component and never uses annotations to select a component. Its output
does not initialize or consume a cohort. The Rust importer pins that manifest
and its actual adapter program, then maps each eligible evidence's `SUPPORTS`
or `REFUTES` label; aggregate `DISPUTED` never becomes a binary gold label.
Neutral evidence remains in the complete masked feature/component graph and
is excluded from binary scoring. No human-facing output contains gold.

Preparation reuses the original fenced holdout CAS, binding domain, private
files and independently retained witness. Existing source namespaces and old
Consumed/Unknown records cannot be overwritten or retried. Source-native
qualification of this adapter is not actual final-holdout qualification: new
cohort initialization remains pending a runnable original paired provider with
genuine reference/candidate outputs, monotonic costs, retention observations
and exact registered unlearning evidence, followed by independent O/E and S.
Source invalidation and CURRENT delivery denial can establish structural
withdrawal; they do not establish removal of information from model weights.

The Linux production facade now has `evaluate_protected_observer_transport`
for an original immutable O cut. It takes the same original locked CAS path,
independent custody witness and registered cut path. The manifest comes from
the original witness's private-gold digest; the binding is recomputed in the
original custody domain. Before reading observations, it replays the held CAS
descriptor with the witness minimum and matches the complete original plan,
sequence, use and journal head. A caller receipt cannot authorize release. The
cloned descriptor retains the same physical lock, uses positional reads without
moving the writer cursor, and does not create a second owner or reset a fence.

`encode_signed_paired_observation_transport_v1` transfers the original binary
O signing payload and existing evidence wire. Decoding does not authenticate
it: the registered runner rechecks current G/O trust, clock, independent O
signature, complete graph, monotonic observations and unchanged frozen metric
gates. Independent E qualification still publishes through the original durable
evidence sink. Missing or invalid post-consumption transport preserves the
Consumed obligation; ordinary evaluation refuses another execution on replay.

This is a concrete protected transport consumer, not an installed scientific
measurement result. The fresh public-development encoder route, actual numeric
candidate/reference measurements, retention and structural-withdrawal producer,
and independent E normal-role entry remain required before the new Climate
cohort is initialized or consumed. No scalar receipt or hash establishes a
passed metric. Rejected and Insufficient results must preserve the same original
costs, profile thresholds, consumption history and terminal evidence.

The normal independent evaluator now exposes `--paired-review ROOT_CONFIG`.
Root publishes the original already-sealed execution together with feature-only
source records and prespecified fold inputs. Transfer is bounded to 128 MiB
and 16,384 items per native input list; larger sources are rejected. E derives dependency components,
freezes the existing paired plan, verifies the original G/O registration and O
observation signatures, and recomputes the existing estimator and metric gates.
It signs only the original `hepta.eval.paired-supervised.independent-review.v1`
preimage. The shared decoder is crate-private and never returns a public sealed
receipt constructor. Original V1 signing domains and byte encodings are unchanged.

`hepta.fixed-paired-review-config.v1` pins the actual immutable E executable,
UID/GID, E private key path, Root public key, publication path/SHA, scope,
objective, original distribution generation and authority epoch. Its five denied
paths cover original gold/CAS and the other role keys. The existing E launcher
requires an empty supplementary group list, all capability sets zero,
NoNewPrivileges and its bounded `hepta-fixed-calibration-eval-*` service cgroup.
Only E holds the E seed. Public publication/config ancestors are Root protected;
E receives no Root CAS descriptor, gold permission or O key. Root keeps CAS0600
and the original locked file description through final publication.

The result remains an independent review with `qualified=false`. The final
original custody runner must compare its actual original execution and G/O/E
current bindings before persisting the original FULL evidence sink. Root metadata
or a transferred consumption receipt does not establish physical custody for E.
This source entry does not claim an installed scientific evaluation, a current
encoder development batch, or consumption of the 91 new Climate components.
The after-CAS O measurement producer and real G/O/E public development run remain
the next composition step; a genuine Rejected or Insufficient result is valid.


The normal `hepta-fixed-product-evaluation --paired-preregister ROOT_G_CONFIG`
entry runs as the original unprivileged Generator role, in its Root-managed
`hepta-native-generator-*` service (one CPU, 256 MiB, 16 tasks, empty groups,
zero capabilities and NoNewPrivileges). The independent E and Root custody
continue to execute their two distinct normal binaries and private keys.
The Root policy pins this G executable, the original trust scope and epoch,
the protected source template, its own key, and five physically inaccessible
custody/other-role paths. No arbitrary payload-signing operation is exposed.

`tools/hepta_encode_paired_plan_inputs.py INPUT_JSON` prepares the original
unsealed native inputs from the explicit declarative JSON schema. It supplies
no default gates, clock, receipt or signature. Each fresh G template has zero
candidate/baseline input slots. G validates the complete graph and native gates
before it requests any physical input; only the independently registered closed
`PublicDevelopmentMeasurementOnlyV1` batch accepts that G MainPID. G records
actual 512 Q24 features, exact original numeric input lines and the conservative
entire encoder/backend before/after accounting. The original G plan signature
binds all these measurements through the typed input-contract digest.
The new batch has one original monotonic total budget of at most 120 seconds;
encoder requests also retain their own existing bounded server deadline.
Original Goal deadlines, grants and final-holdout states are unchanged.

This entry is preregistration, not a product qualification or final-holdout use.
Normal G role and fresh encoder deployment remain to be verified. Original
custody after-CAS numeric execution, real retention/source-withdrawal consumers,
independent E review and the original FULL evidence sink are required before
initializing or consuming a new Climate cohort. Nonzero hashes or prepared
configuration do not satisfy those consumers. Future candidate generations use
the existing independent E, selection and Artifact CURRENT path; the limited
V2 generation-one abstention lease does not replace that promotion evidence.
