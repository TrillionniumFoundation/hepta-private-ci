# Ordinary PQ effect entry integration

Source: `1993db5510afb9764a4a4a60e5bd0f48862411ab`, based on
`4c93a641945044f904a656cbf1d23e358a074d52` (#4497). The ordinary initial
host/CURRENT files at that base match the relevant files in the supplied
[audit at e0b4c82](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e0b4c82e129d42d98cb9a98bf97fe41d1e3b1b53/qualification/learning-generations/hepta-pair-v8-source-20261104/ordinary-authorization-audit.json).
This change does not rewrite that historical audit result.

## Actual production entry points

The existing `UnixFinalUseAuthorizer::open` now requires explicit
`authentication_profile: ml_dsa65_v2`. Missing or classical profiles fail before
contacting an issuer, clock or frontier, or opening durable authority state.
The private-file checks and configuration bounds remain. Existing classical
snapshots are not automatically migrated or reactivated.
The explicit classical `from_config` constructor remains capable of authorizing
effects; it is not a read-only history API. This patch closes the shared `open`
route used by the worker binary and the initial/trained host preparations.

The public initial-material constructor requires material admitted by PQ CURRENT
and selector signatures.
The shared ordinary/Cell trained-model preparation path requires a PQ bootstrap
verifier before reading parameter bytes or contacting the Cell/FinalUse effect
owners. The existing cross-layer profile agreement checks still apply.

All four FinalUse entry implementations reload the configured external frontier.
The comparison includes the complete profile-bound nonce and revocation digest,
not only epoch/revision. Divergence or unavailability fences the retained owner;
refusal does not refund a consumed nonce. Getters stay local, while claim/update
retain their existing atomic external CAS. Every public token, consumer, effect
and dispatch API also requires the exact authenticated claim head. The narrow
contracts change and two entry tests come from #4729 at
`ef5723af6a04c7c74fa8a32ab34acdfd49913233`; its other changes are not included.

Existing canonical PQ signing domains and serializers are reused. This change
does not define a new common signed envelope or qualify network/genesis binding
across all six authorization surfaces.

A frontier observation and a remote provider effect are not one distributed
transaction. Another owner may advance after the observation, including during
the protected clock call. Closing this interval still requires a shared admission
lease/provider transaction. An admitted effect is not cancelled by this patch.

## Original ordinary callers

The existing initial lifecycle, public-initial Agentd and neural-study entrypoints
use canonical PQ owner/selector signatures and the original FinalUse loader.
Study generator, evaluator, observer and selector have distinct keys. The root
distribution, training ledger, witness, child CURRENT and installed descriptor
use the same PQ profile; clock and learning frontier have distinct pins.

Original claim counts, resource limits, model inputs, deadlines, assertions and
explicit cleanup remain. Post-load expiry/revocation controls advance the actual
signed clock after a complete Completed record in the original inference
journal, and still require the real retained load for cleanup. They do not use
the legacy callback that PQ preparation ignores.

These controlled keys/services are test fixtures, not independent deployment
custody. The public session reopen control reopens CURRENT/Agentd using fresh
authority fixtures. A separate ordinary PQ-config test reopens the same FinalUse
state and frontier and checks the spent nonce. Those are different claims.

## Verification and retention

`qualification.json` distinguishes current results from observations preserved
in the earlier tool transcript. Before an execution-environment reset, the
original leaf command ran 333 tests in five binaries: 330 passed, three existing
Unix trust-service tests failed with EPERM, and one existing ignored test was
skipped. Both new claimed-head tests (eight APIs each) and all four new external
frontier tests passed. The four frontier identities first failed against the
original production implementation; its default retry produced eight failed
executions. The earlier `--lib` selection (330 run/327 passed) is a separate
selection and is not added to the final count.

The full host `cargo check --tests` also passed. The selected host native tests
had only started building when the environment reset; their result is unknown,
not passed. The transient raw logs and build cache were lost. The four source
commits were recovered intact from GitHub and retained in PR #4812; fresh runs
are recorded separately. No missing raw log is represented as an available file.

Run the commands in `reproduce.sh` on the fixed source with Rust 1.96.0, just and
cargo-nextest installed. It preserves each command's status and does not convert
Unix-socket failures into skips. A successful compile is not a native test pass.
The pinned real-model study additionally requires its original model, worker
source and codex executable configuration; it is not run by the small regression
selection and is not claimed as a result here.

## Remaining surfaces

Initial artifact selection retains its original selector trust snapshot and
rechecks fresh CURRENT; it does not observe a selector revocation issued after
material creation. The learning evidence `Selector` role belongs to a different
signed trust domain. Its frontier is not an authority for
`ArtifactSelectionTrustV1`. Closing this gap requires an explicit root-signed
binding of selector trust, registry/scope and generation, a current authority
provider, and a retained anti-rollback floor at ordinary initial use. Merely
reusing the other role's root would expand permissions without authorization.
The [proposed selector-currentness contract](selector-currentness-contract.md)
sets out this missing binding and its ordinary business acceptance controls. It
is a design proposal, not an implemented gate or a production qualification.

| Surface | Boundary of this change |
| --- | --- |
| Accounts, payments, jobs, settlement | No Chain code or AuthBus settlement wiring is changed. Current-key, nonce, balance/debt and portable-settlement qualification remain source-specific work; inference journal receipts do not qualify monetary settlement. |
| Identity, discovery, resource requests | No public key becomes a resource/recovery capability. Network/session and resource-owner qualification remain separate. |
| Cell publication and CURRENT | Ordinary neural initial/trained consumers require PQ CURRENT/selector authority. Publication and dynamic trust-root/selector revocation still require their own complete coverage. |
| FinalUse/runtime | External state and exact claim head are checked at actual entry. Distributed admission and other modules' explicit classical constructors are not fully migrated by this patch. |
| Governance, updates, recovery | No governance-root, network-activation or recovery-policy change is made. |
| History, cold start, import | Historical readers remain available; ordinary runtime configuration cannot silently activate a classic authority directory. No implicit classic-to-PQ migration is introduced. |

Overall qualification remains **HOLD**, with production activation false.
Independent custody/WAN execution, the real model's installed business use,
complete rotation/recovery/migration and whole-chain PQ claims remain unclosed.
No remote CI result is used or awaited.
