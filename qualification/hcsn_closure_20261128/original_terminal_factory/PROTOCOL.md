# Original production owner to terminal learner

This engineering slice reuses the exact installed Agentd production host and
its recovered Memory store. `DurableCognitiveStore` is the existing Memory
implementation's re-export; this slice creates no store or migration.

The embedding must already own an activated, witnessed `LedgerWriter` Arc.
The factory neither creates nor recovers a ledger, trusts a JSON declaration,
signs an Evaluator payload, grants Replay, or synthesizes authenticated events.
The existing workspace binding digest is derived from Agentd's own identity.

One current production host may construct one terminal owner. An atomic claim
is never cleared by dropping a handle, so the same host cannot reset its task
cache by building another owner. An already configured terminal bootstrap is
refused before verification or allocation, using the existing config guard.
The config must contain this exact host object,
with the same agent and spawn generation. The original live writer verifier is
checked before and after assembly under one caller-supplied absolute deadline,
at most 30 seconds from entry. Source admission and all subsequent existing
Replay revalidation paths also check that retained writer before and after the
coherent Memory policy read. Revocation or checkpoint fencing refuses use.

The factory installs the ordinary terminal owner/bootstrap and its fixed paired
metadata policy, returning the terminal handle and actual late Evaluator inbox.
The paired runtime must additionally attach its original delivery receiver and
same session end; the embedding must actually consume that inbox. Missing existing
Ledger owners or signed evidence remain an explicit production integration gap.
No caller can obtain them from a path, a captured trace or a fixture.

Validation will use the unchanged native crate via its single engineering gate
owner and the remaining shared 3,600-second pool. Meaningful new controls cover
exact host and workspace binding, one owner per production host, retained live
writer refusal after assembly, and original absolute deadline. Test authorities
and test Ledger events are synthetic and never count as genuine human consent,
new learning progress, adoption, useful-work value or payment. No E1–E6 episode,
training corpus, previous statistical comparison or closed scientific budget is
reopened by these checks.
