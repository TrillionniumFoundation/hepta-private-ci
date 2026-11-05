# Original Desktop owner succession

The joint Notes and Calculator composition retains the original Root, authority
lease registry, issuer, CognitiveStore and protected writer. New finite
generations reuse those owners and their canonical state. They do not create
another signing key, authority epoch, operation ledger or writer.

## Policy transition on the original issuer

`src/deployment_desktop.rs` defines `RootDesktopPolicy` for one actual Session's
distinct Notes and Calculator targets and bounded grant lifetime.
`replace_registered_desktop_policy` requires actual Root and an already
registered successor. It moves both application policies in one full issuer
state compare-and-set.

The transition checks the live original writer and retained proof under the
original locks. It accepts the exact complete predecessor pair or the already
published exact complete successor pair. A mixed or ambiguous pair refuses.
Every other policy, signing key, sequence, revocation head and writer proof is
preserved. Old signed receipts keep their meaning. The transition dispatches no
effect and never renews an old operation.

A durable publication may precede an error reply. Reconciliation must keep the
same successor pair; it cannot choose a new target as an automatic retry.

## Finite issuer continuation

`src/authority_host_issuer_renewal.rs` provides explicit actual-Root prepare and
commit APIs. Preparation opens the existing protected issuer, checks its key,
canonical lease revision, epoch and revocation state, reads the original clock,
and returns a bounded same-ID revision + 1 postimage. It changes neither the
binding nor the key, directory or epoch.

Root persists this exact plan before commit. Commit accepts only the exact
canonical predecessor or the exact already-installed postimage, then calls the
original registry CAS even for a lost-reply retry. A missing/pruned record,
changed binding/revision/epoch, revocation, or expired plan refuses. Retry never
recomputes a later expiry.

After success, the launcher pins the new revision and reopens the SAME original
issuer. Old service instances still hold the old revision and fail closed. The
returned canonical lease record is administrative data, not a FinalUse token.

## Joint Root startup

`src/root_desktop_startup.rs` keeps separate fresh and recovery entries. Fresh
schema v1 excludes previous recovery. Recovery schema v2 requires a strict
Notes/Calculator previous pair through `desktop_previous_recovery`; explicit
null, partial, foreign or extra-authority fields are rejected.

The successor must already have original writer rotation and physical material
recovery. The same retained Root observes physical Current. Its actual new
Session reservation supplies the successor targets. Only then does
`authority_host_desktop_successor` invoke the atomic policy-pair transition,
followed by both original admissions and sealing of the inherited deployment.

The Root startup method does not initialize an issuer, rewrite an old operation,
accept a caller-provided Current, or grant an old helper a new effect route.

## Original application recovery

The original protected Agentd writer resolves previous-record selectors from
the retained signed Desktop source and canonical ledger. Old target identity,
operation, thread, callback, destination and intent remain bound to the original
record. A true complete empty cut is distinct from an unknown, timed-out or
mismatched lookup.

`calculator_recovery_process` and the existing Notes process factory pin a
sealed helper ELF and admit only observation and exact terminal retirement ACK.
Calculator's `ProductionCalculatorRecoveryTarget` reuses the original terminal
settlement and retirement permits; it does not construct permits from helper
JSON or install a dispatch/FinalUse target.

A historical Committed operation alone does not prove retirement. The original
source owner must retain actual target-ACK evidence before a later generation
may skip it. Root administrative files and a checkpoint ACK that preceded the
target ACK cannot stand in for this proof. The integrated reader must fail
closed if the required original evidence is absent.

## Product integration and bounds

The Desktop product keeps one actual Root lock across generation-specific
preparation directories, consumes a spawn once, and verifies physical owner and
Session retirement before continuation. The product requires durable Notes and
Calculator state and rehashes both original helper ELFs. Its new joint
composition is distinct from older joint metadata without Calculator storage.

Recovery is same-boot and source-pair specific. Finite lifetime and grant bounds
remain unchanged. Original registry capacity, real owner exit, source identity,
physical Current, admission, FinalUse and actual App acknowledgements still
bound progress. These entries do not qualify unlimited service, account capacity,
cross-boot migration, native Asterinas or a physical Android deployment.

## Verification

Use Rust 1.96 and the original `just test` entry point. Meaningful component
coverage includes original registry/signer/disk pair CAS, two successive writer
transitions followed by issuer revocation, same-postimage renewal retry, old
revision fencing, SQLite recovery of old Calculator operations, sealed helper
restrictions, and strict fresh/recovery profile separation.

The complete original caller inventory and protected guards must pass on the
final combined source. Run the affected original packages, then the required
`just fix -p codex-hepta-agentd` and `just fmt` workflow. Compiler and test
receipts must retain their exact source identity and feature selection.

Source checks and fixture tests do not establish final product acceptance.
Qualification additionally requires an installed same-source-pair Linux run
through at least two real successor cycles, actual old-result recovery/retirement
and revoked-authority refusal. This integration is not considered complete
until those distinct receipts exist.

## Fixed effect policy and bounded recovery

Successor writer local generations and issuer lease revisions advance independently. The original frozen effect policy generation, model/runtime/prompt/artifact bindings and signed operation semantics remain unchanged across a same-source pair. A new owner never relaxes the comparison of an old operation against those original signed bindings.

The original complete retained-request cut is bounded to 1,024 requests and 32 MiB; exceeding either bound refuses recovery. Two observed successor cycles qualify only that bounded scenario, not unlimited operation or a cross-version database upgrade. Queued, Rejected and RolledBack records do not prove target retirement; the joint selector refuses them until an original owner evidence path establishes the required fact. Committed historical records are skippable only after the original writer retained an actual target retirement ACK.

The original Desktop owner acknowledges its real Current after both authenticated application handoffs and before atomic installation. This consumes the original launcher deadline. Objective sender construction only checks its retained writer and process binding; it writes no rows. Recovery selection performs read-only Current observations and never publishes a new cut.
