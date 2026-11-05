# Evidence recovery V2 integration qualification

Status: **HOLD_NO_GO**. This record contains source integration and a runnable
qualification procedure. No Rust/native test, repository formatter, Clippy fix,
or execution of the reproduction script is recorded as passed here.

## Fixed source

- Repository: `TrillionniumFoundation/hepta-private-ci`; existing Draft PR #4812.
- Baseline: `3a8e50ddd79ec3e52ca58157323726c37069202c`.
- Integrated code: `29fcd2e88654d5bec2bf30134cc030b5bfa7831b`.
- Integrated code tree: `9653293a81dfda7f17c12a54fd7bd5f4170ea867`.
- Reused V2 source: PR #4729, `ff280f268f4f2d2287109b7af7f8c22ba790df6c`;
  its later evidence-only head is `a53e6e2a7aacf4784e48c680a5980960a17d8a35`.

The code commit changes exactly the fourteen paths listed in `manifest.json`.
Each entry records baseline and candidate Git blob identities, SHA256 and byte
length. Eleven files are byte-identical to the upstream source, including the
cold-open provenance test missing from #4812. The other three preserve the
current FINAL_USE document and JSON ordering: FINAL_USE gains a V2/provenance
section; the two maps change only six V1 type references to V2. No dependency,
SQLite migration, PQ profile, resource threshold or acceptance status changes.

## Defects addressed

The baseline recovery snapshot commits migration, qualification and AuthBus
replay state, but omits provider effect intents, uncertainty and ACKs. A valid
older database that loses only effect history can therefore match the same
snapshot. V2 includes all three effect tables in the same SQLite read transaction
as the other projections. It commits table identity, sequence, stable effect
key, verified record digest, timestamp and ACK source; primary-key pages cover
the complete bounded history. The one-million-effect-row bound fails closed.

The baseline also enforces ACK provenance at live append but lacks the matching
cold-open check for a status-lookup ACK followed by a dispatch-response ACK when
there is no uncertainty marker. The included guard restores this startup
invariant and retains valid dispatch-then-authoritative-status histories.

The actual `EvidenceHost::open` caller already invokes
`verify_evidence_recovery_frontier` when its recovery-frontier configuration is
present. That verifier now reads V2 and signs/verifies the V2 domain. It compares
the full snapshot before binding the store identity. This integration is not
limited to an unused snapshot API.

## Compatibility and scope

The database lineage and SQLite schema do not change. Public snapshot/frontier
types, signed JSON schema versions and the signing domain change to V2; there
is no alias that permits V1 semantics under a V2 name. A real valid V1 signature
is intentionally refused. An operator must obtain a newly reviewed and signed
V2 checkpoint from the recovery authority; a recovered local database must not
be treated as authority to upgrade its own checkpoint. The historical
`RECOVERY_FRONTIER_V1.md` filename is retained so existing links still resolve.

The signer trust file remains schema V1 and the signature/key remain Ed25519.
This is **not a PQ recovery root**. `EvidenceHost::open` still takes optional
frontier paths; this patch does not make the frontier mandatory for every
Agentd configuration. The strengthened comparison applies to the configured
signed-frontier admission path.

A file outside Agent home does not establish an independent physical rollback
domain or authenticated freshness. Remote latest-state reads, monotonic CAS,
durable acknowledgement, independently operated custody and whole-host rollback
qualification remain open. Provider-effect coverage is for `hepta-evidence`;
the separate AutomationStore, FinalUse atomic consumption and the live
frontier-to-clock-to-provider execution race remain outside this change.
No global A1/A2/A3 or B/C/D/E gate is closed by this integration.

## What was checked

GitHub source fetches were pinned to the full baseline and upstream commit IDs.
Git SHA1 and SHA256 were recomputed in memory, first checking known hash vectors
and then the upstream manifest. All fourteen candidate source identities were
also fetched and rehashed by the parent before publishing the code commit.
Both JSON documents parse and retain byte ordering except for the six intended
type-name substitutions. FINAL_USE retains the entire baseline text as a
prefix. These are source checks, not Rust compilation or independent running
acceptance.

The retained full-repository V1 symbol/domain scan and the complete candidate
closure audit identify all Rust callers and both metadata maps. In candidate
Rust source, the old signing domain appears only in the real legacy-signature
negative fixture. Historical document links remain intact. The live caller
`evidence_host.rs` is unchanged; its identity is recorded in the manifest.

The execution service was unavailable during integration. Earlier observations
of AF_UNIX `EPERM` concern host/service execution, not a pass or failure of these
new owner tests. All native RED/GREEN results, `just fmt`, `just fix`, and the
new reproduction script itself are **NOT_RUN**. Older #4729 tests do not qualify
this source combination.

## Reproduce the owner counterexamples first

Use a clean checkout of the evidence-only successor to the code commit above.
Supply that checkout's full commit SHA explicitly. The script verifies HEAD,
the pinned code tree, all fourteen source hashes, and that later changes are
confined to this evidence directory. Choose a new output directory outside the
checkout. It retains logs and the test-only baseline worktree for review.

```bash
python3 evidence/recovery-v2-integration-20261105/reproduce.py \
  --candidate FULL_CHECKED_OUT_COMMIT_SHA \
  --output /absolute/new/recovery-v2-owner-receipt \
  --phase owner
```

The RED tree is the exact baseline plus the same two owner test files and their
two module declarations, with no production-source fix. The script verifies
that only these three paths differ. The seven real SQLite/store cases exercise
effect-only rollback, intent/uncertainty/receipt changes, ACK provenance, history
after the first 256-row page, changed JSON with a retained digest, and a valid history control.

The intended baseline result is **six assertion failures and one positive
control pass**; the candidate intends all seven passes. Those are expectations,
not observations. The script checks actual named nextest status lines and exits.
A build error, permission failure, zero tests, unexpected test selection, or
unrecognized output cannot be accepted as a successful RED or GREEN run.

The exact selected command used in both source trees is:

```bash
just test -p codex-hepta-evidence --locked --lib --retries 0 \
  -E 'test(recovery_effect_frontier_tests::) | test(provider_effect_recovery_provenance_tests::)'
```

Run it from `codex-rs`. Repository `just test` already supplies `--no-fail-fast`;
do not duplicate that flag. The script sets only `CARGO_BUILD_JOBS=1` for compile
concurrency and preserves normal repository features, dependencies and linker
configuration. It does not substitute a mock crate or diagnostic linker.

## Remaining native qualification

Each invocation below uses a separate new `--output` directory. The script's
`--phase full` runs `just test -p codex-hepta-evidence --locked` after selected
owner cases pass. `--phase signed` runs the two real Ed25519/file/verifier cases:

```bash
just test -p codex-hepta-agentd --locked --lib --retries 0 \
  -E 'test(evidence_frontier::tests::recovery_frontier_)'
```

These tests require Unix file-identity behavior, but do not bind an IPC socket.
They verify refusal of a correctly signed V1 checkpoint without binding store
identity and cryptographic authentication of both new V2 effect fields.

`--phase product` runs the real Agentd startup fixture:

```bash
just test -p codex-hepta-agentd --locked --test kernel_evidence_product \
  --retries 0 -E 'test(signed_recovery_frontier_)'
```

Its three cases cover exact-current admission, a valid older qualification
database and a valid effect-only older database. They require real Unix IPC.
A denied socket must remain blocked/not qualified; do not bypass permissions
or convert the failure into a pass.

`--phase format` runs `just fmt --base BASE_SHA --check` on this committed
change, avoiding an empty-diff formatting success. Repository instructions
still require normal `just fmt --base BASE_SHA` after source editing and scoped
`just fix -p codex-hepta-evidence` / `just fix -p codex-hepta-agentd` before
finalizing a large Rust change. None ran for this integration. Preserve any
resulting source identity changes and do not attribute tests from an earlier
source tree to a later one. `--phase all` sequences format check, RED/GREEN, the
full evidence package, signed-file cases and Agentd product cases; it remains
a scoped run and never marks whole-chain or independent acceptance complete.

Receipts retain `HOLD_NO_GO` even when a selected phase succeeds. Review actual
names, counts, logs, exact source identities and the unresolved deployment
conditions before making any broader acceptance decision.
