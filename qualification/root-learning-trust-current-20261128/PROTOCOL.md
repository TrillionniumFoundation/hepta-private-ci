# Original Root current selection: prospective source slice

Base: complete input codec `8a39705ad59d188962d88ebd689884b27889d78a`.
This slice connects explicit `--learning-trust-current-intent` to the consumed
original Prepared fresh session, its original paired profile, actual Root
credentials, process/logind binding, issuer, writer proof and configured policy.
The same complete private input codec becomes a production dependency. Missing
original owners, policy or external inputs are rejected; none is created here.

The original Registry holds the live issuer/writer fence; its short-lived lease
is not a durable current pointer. Registry pruning removes expired payloads and
epoch advance clears retired IDs. An earlier local, unexecuted registry-pointer
prototype was therefore rejected before source publication. The sole selection
commit point is create-only `HostAuthorityFrontierStore<Vec<u8>>::initialize` in
the original Root state directory, retaining and reading back the complete
canonical record. The fixed slot binds actual owner, workspace and logical Ledger;
generation, Root key, scope, objective and writer generation cannot create another
slot for that Ledger. A separate original policy binds Root, scope and objective.

The record contains the full acknowledgement declaration, original signed-trust
identities and validity, writer proof, generations and selection revision.
`selection_expires_at_ms` records the historical administrative admission window;
it is not a current-record TTL. Existing records refuse initial selection even
after live leases expire. Later rotation must read this same full record and use
the original full-value CAS; it must not enumerate orphan metadata or choose the
largest generation. This slice does not implement rotation or Ledger recovery.

Lock order is original Registry, issuer request mutex, then independent Root
publication lock. Signature, exact policy, writer proof, epochs, original time
and absolute deadline are checked before publication and again afterward.
Synchronous fsync is not preemptible. Any error after publication starts is an
uncertain outcome requiring original Root observation; there is no automatic
retry or rollback. The original store only forgets its durability cache on error;
this slice does not claim a permanent global fence or transactional human checks.

First selection is an administrator's explicit choice, not a cryptographic proof
of globally newest trust. The acknowledgement is an independent Root declaration,
not observed consumer utility. Protection excludes Root or whole-host rollback.
Root write authority is not exposed to Agentd, and late human Train consent,
original material ownership and Evaluator signing remain separate requirements.

Three prospective controls cover stable namespace/policy separation, exact owner
and acknowledgement rejection, and real CLI refusal before descriptor/file use.
No Cargo, Root provisioning, native control, fit or scientific run is performed.
Actual formatting and scoped original source checks are recorded separately;
full Root execution, current rotation and recovered-Ledger consumption remain open.
