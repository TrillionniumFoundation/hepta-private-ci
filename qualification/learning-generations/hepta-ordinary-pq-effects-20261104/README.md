# Ordinary PQ effect entry integration

Delivered source: `7335636b2cbde4077e354dcb3156a04b9ee6e8a9`, based on
`4c93a641945044f904a656cbf1d23e358a074d52` (#4497). The ordinary initial
host/CURRENT files at that base match the relevant files in the supplied
[audit at e0b4c82](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e0b4c82e129d42d98cb9a98bf97fe41d1e3b1b53/qualification/learning-generations/hepta-pair-v8-source-20261104/ordinary-authorization-audit.json).
This change does not rewrite that historical audit result.
The native results below were obtained at
`1993db5510afb9764a4a4a60e5bd0f48862411ab`. Later changes and their separate
verification scope are recorded explicitly below and in `qualification.json`.

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

The existing initial lifecycle, public-initial Agentd and neural-study tests now
drive the original entrypoints with canonical PQ owner/selector signatures and
the original FinalUse loader.
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

The fresh native commands used source `1993db55`; their logs are hashed in
`qualification.json`. These results are not aggregated with earlier runs.

| Check | Actual result |
| --- | --- |
| Contracts + learning-artifacts, five binaries | 333 run, 330 passed, three existing Unix trust-service failures with EPERM, one existing ignored test skipped; exit 100. All six new FinalUse controls and the three public-initial admission controls passed. |
| Host, default resumed link | Link failed with SIGBUS; zero tests executed; exit 101. The cause of SIGBUS was not established. |
| Host, optional diagnostic link | Six selected tests ran: three passed, three failed with EPERM; 178 tests reported skipped by the filter/existing ignore selection; exit 100. |
| Required scoped `just fix` | Failed while creating a dependency fingerprint directory with ENOSPC; exit 101. No successful lint/fix result is claimed. |
| Repository `just fmt`, `just fmt --check`, whitespace check | Passed, exit 0, including the later source changes. No Rust tests were rerun after fix/format. |
| Pinned real-model ordinary training/install/next use | Not run. |

The three passing host controls check ordinary `open` profile refusal,
non-reactivation of an existing classical state, and PQ study-role wire
verification without installation activation. The same-state PQ reopen,
service cleanup and training-ledger reopen controls failed with EPERM. Their
lifecycle assertions are not accepted as passing.

The diagnostic host binary used `--threads=1 --strip-debug
--no-mmap-output-file` at the final link only. It used the same Rust source,
test selection, dependencies and runtime checks. This is a different link
configuration and does not establish a successful default native run. An earlier
fresh build also lost its execution session during dependency compilation; that
attempt remains unknown, with no test passes attributed to it.

The parallel commit `484ce165522026d915c4cf526cd7df2effab632c` is preserved.
It additionally refuses equal canonical clock/frontier paths before opening
trust clients or the owner. Its new/expanded tests were not executed in this
run, and the `1993db55` results do not cover that change. Its source/format
receipts are retained in
[the endpoint-separation record](../../../evidence/pq-final-use-endpoint-separation-20261104/README.md).
The subsequent `7335636b` changes only clarify the effect-capable classical
constructor and add two argument-name comments.

The earlier environment's full host `cargo check --tests` passed on `1993db55`,
but its transient raw logs were lost at reset. Its leaf run had the same
333/330/3/1 counts; an earlier `--lib` selection had 330/327/3/1. Neither is added
to the fresh counts. The four frontier identities first failed against the
original implementation (eight executions with its original retry). These
historical observations remain separate from the retained fresh logs; missing
raw logs are not represented as available files.

Run the commands in `reproduce.sh` on the fixed source with Rust 1.96.0, just and
cargo-nextest installed. It preserves each command's status and does not convert
Unix-socket failures into skips. A successful compile is not a native test pass.
The pinned real-model study additionally requires its original model, worker
source and codex executable configuration; it is not run by the small regression
selection and is not claimed as a result here.

`reproduce.sh` runs the default link configuration. To reproduce the optional
diagnostic configuration separately, use the checked-in wrapper with the LLVM
linker used in this run. Use a fresh build directory so Cargo cannot silently
reuse a binary from another link configuration:

```bash
qualification_repo=$(git rev-parse --show-toplevel)
qualification_diagnostic=$(mktemp -d)
mkdir "$qualification_diagnostic/bin"
ln -s "$qualification_repo/qualification/learning-generations/hepta-ordinary-pq-effects-20261104/host-test-linker.sh" "$qualification_diagnostic/bin/cc"
PATH="$qualification_diagnostic/bin:$PATH" \
CARGO_TARGET_DIR="$qualification_diagnostic/target" \
CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 \
just test -p codex-hepta-infer-worker-host --lib --locked --retries 0 \
  -E 'test(ordinary_open_) | test(ordinary_pq_) | test(pq_study_role_wire_) | test(ordinary_study_pq_)'
```

The recorded diagnostic run reused the incomplete default build's object cache
and reran its failed link. This fresh-directory reproduction intentionally
rebuilds dependencies. The wrapper targets only the host library test binary
and leaves other links unchanged. It does not enable Unix socket permissions.

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
