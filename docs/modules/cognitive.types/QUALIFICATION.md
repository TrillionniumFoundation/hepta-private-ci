# cognitive.types qualification and migration supplement

This implementation supplement accompanies, rather than replaces, `TECHNICAL.md`, the existing implementation map and execution dossier. It records API interpretation, reproducible checks and outstanding evidence boundaries. No completion or release authority is created here. The invariant table is generated from `INVARIANTS.json`; candidate results belong to external immutable artifacts.

## 1. Value layers and owner responsibilities

Raw Rust/Serde DTOs remain available for transport and historical compatibility. Constructing or deserializing a DTO does not authenticate a producer or establish the complete structural invariants. `Validated<T>::new` and `decode_validated_wire_v1` create an immutable structurally checked value. A caller cannot obtain mutable access through the wrapper; extracting the DTO consumes that proof wrapper.

`ManifestCheckedSpanV1` and `EventCheckedBindingV1` additionally check the supplied asset manifest or event context and borrow the checked inputs. They do not prove that the supplied context came from an authorized owner. The actual asset/source owner must supply its current manifest, scope, revocation frontier and producer identity. Raw IDs, booleans and hashes cannot serve as substitutes for those authenticated observations. Revalidate immediately at physical read, write, context delivery, training or artifact-use boundaries.

Logical uniqueness is separate from canonical sorting. Provenance uses `(source_id, source_revision)`; recall selection uses `(event_id, revision)`; active nodes and threshold proposals use `node_id`; activation paths and weight proposals use `(source_node_id, target_node_id, relation)`; topology nodes use `node_id`. A conflicting value under an existing logical key rejects, rather than becoming a second observation through full-value ordering. Record and write-receipt transitions retain their explicit scope, purpose, profile, generation and predecessor checks in `transitions.rs` and `lane_c.rs`.

## 2. Frozen and schema-bound digest profiles

The frozen profile `canonical_contract_digest_v1` remains the interpretation of existing canonical V1 consumer bindings and golden vectors. The schema-bound profile `canonical_contract_digest_bound_v1` additionally binds exact schema, envelope version, contract identity and canonicalization algorithm through framed components. Unicode scalar sequences are preserved, not normalized in place. These profiles deliberately yield different digests for one payload.

Never test new/old semantic equivalence by comparing those raw digest bytes. `CanonicalHandoffV1` compares checked canonical projections under one explicit common semantic interpretation and binds the operation, consumer, source identity, snapshot and compatibility posture. Its expected projection must come from the responsible owner; comparing a caller's value with itself does not establish authenticity.

The existing store product bridge now retains one private `Validated<MemoryEventV1>`. Its validation recomputes the frozen digest for the consumer binding and the schema-bound digest for the durable binding from that same retained event. It also checks event identity, source revision, operation, consumer, source/snapshot bindings and compatibility digest. This repairs an actual incompatible-domain equality check without changing historical digest functions. `canonical_event()` exposes immutable structural evidence only.

Historical V1 rows and private scopes remain readable under their original interpretation. A profile change requires an explicit consumer migration and compatibility decision, not relabeling an old digest. No V1 source is implicitly converted into Shared Experience V2.

## 3. Existing consumers and physical use

The qualification matrix includes the existing `cognitive.read`, `cognitive.store`, `memory.retrieval`, `compact.engine` and `intelligence.control` packages. The owner group includes the existing Memory and Agentd packages, including `cognitive_store_product_writer`. The store repair changes the existing binder invoked by that product test, not a replacement writer. Snapshot and page leases reject use before opening and at expiry, implementing `[opened_at, expires_at)`.

The central binding matrix is fail-closed. `MemoryEventV1` is accepted only for `cognitive.read`, `cognitive.store` and `compact.engine`; `RecallPacketV1` is accepted only for `memory.retrieval` and `intelligence.control`; forget-propagation receipts remain limited to read, store and compaction consumers. A caller cannot substitute a structurally valid event into a recall consumer merely by choosing that consumer enum. The reviewed migration registry still controls posture independently of payload validity.

Package execution and explicit canonical inputs are not sufficient evidence that every normal production profile obtains authenticated, currently valid canonical inputs. Consumer registrations still distinguish shadow and pending-cutover states; compatibility paths remain available under their registered bounds. Do not mark canonical convergence or default-profile composition true until each named normal path proves source, scope, currentness/revocation, allowed fallback and final delivery. A pure type library cannot grant the missing owner capabilities.

## 4. One immutable source/base pair, two candidate trees

The read-only `cognitive-types-qualification.yml` resolves one full source SHA and one fetched main SHA before fanout. Its native, consumers and owners groups each run exact-head and deterministic synthetic-merge candidates. A merge conflict rejects. The synthetic commit has the ordered parents `[base, source]`, the merge-tree result and deterministic commit metadata.

`run_qualification.py` records source/base/candidate commits and trees, ordered parents, workflow/run identity, runner image and actual toolchain commands. Every command retains its argv, working directory, exit code, timing and SHA-256 of its captured log. The shared command capture terminates the owned POSIX process group on timeout and rejects a zero-exit leader that leaves residual members; its containment limit is specified below. Missing tools and timeouts are `infrastructure_invalid`, not passes. Nonzero exits, missing/empty checks and skipped states cannot satisfy qualification. Final checks reject candidate-head changes, tracked modifications and untracked source files.

Receipts and build targets used by the probe live outside the source tree. Upload failures fail the job. The matrix aggregate requires all groups; qualification does not set product acceptance, activation or release. The workflow has read-only repository permissions and never repairs, deletes, commits or pushes candidate source.

From a clean checkout at the intended source, invoke with full immutable SHAs and an external output directory:

```sh
export PYTHONDONTWRITEBYTECODE=1
SOURCE_SHA=$(git rev-parse HEAD)
BASE_SHA=$(git rev-parse refs/remotes/origin/main)
OUT=$(mktemp -d)
python3 qualification/cognitive-types-v1/run_qualification.py \
  --source "$SOURCE_SHA" --base "$BASE_SHA" \
  --kind exact-head --group native --output "$OUT/native-exact"
```

Repeat with `--kind synthetic-merge` and groups `consumers` and `owners`, preserving the same source/base values. The candidate preparation may detach HEAD but does not update any branch. Use `just test` as the repository package-test entrypoint. The CI matrix installs explicit test-runner versions and records the actual active compiler; setup failures remain unsatisfied.

### 4.1 Closed command capture and check-plan version 3

The existing `run_check` entrypoint now delegates process and log capture to `command_process.py`; native, consumer and owner commands, as well as mutation builds and exact-test experiments, retain that same entrypoint. This changes no command list, package selection, lint strictness or candidate identity. It repairs an observed counterexample: a parent exited zero, the old runner sealed an empty passing log, and its child subsequently appended 14 bytes, invalidating the recorded digest.

The parent exclusively creates and owns each log file; children receive a pipe instead of the writable log descriptor. Existing files and symlink aliases reject rather than overwrite. The selected POSIX runner uses a monotonic deadline, reads at most 64 KiB per chunk, retains at most 64 MiB per command and allows five seconds for leader cleanup after termination. Exceeding the log limit retains a bounded diagnostic prefix with `log_complete: false`; it is `infrastructure_invalid`, never a truncated pass or a killed semantic mutant. Missing programs, deadlines, signals and residual process groups also cannot pass. A properly waited child and an exactly-at-limit complete log remain valid observations.

Every command records `capture_version`, `log_complete`, `process_group_closed`, `log_bytes` and `log_limit_bytes`. Both receipt sealing and six-artifact verification require strictly typed completion facts, the reviewed limit and exact correspondence with the inventoried log bytes and digest. Check-plan version 3 rejects earlier receipts as evidence for the new capture contract; older evidence remains historical and is not rewritten. The evidence schema and frozen cognitive wire/digest profiles are unchanged.

This is bounded pipe capture and owned-process-group cleanup, not an OS sandbox or a proof that every process on the host has stopped. Processes that create a separate session/group, including independently supervised nested commands, require host-level containment for whole-tree cancellation; file-system mutation by an escaped or unrelated process is not prevented by this helper. Unresolved cleanup remains nonpassing. Current owner authentication, revocation and final-use checks are not cached or supplied by the runner.

The focused regression entrypoint is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s qualification/cognitive-types-v1 -p 'test_*.py'
```

For development without the complete repository, the narrower `test_command_process`, `test_run_qualification` and `test_verify_receipts` modules can be run explicitly from that directory. Those process/fixture tests are not Rust, cross-language, source-mutation, authenticated product or selected-host capacity qualification. The full command plan and both fixed candidate trees remain mandatory for module acceptance.

## 5. Cross-language, hostile-input and source-mutation evidence

`examples/canonical_probe.rs` invokes the actual 16 registered production decoders; it defines no replacement protocols or authenticated owner. On success it checks exact canonical roundtrip and emits both digest profiles. A structural rejection is a machine-readable violation with process exit 2. Crashes, missing tools and malformed output are not accepted as negative-test successes.

`quality_checks.py` consumes the retained 12 V1 and four V2 golden payloads, checks their frozen digests, and compares actual Rust output with independent Python and Node digest calculations. Additional cases cover full-width unsigned integers, Unicode scalar preservation, JSON pointer escapes, noncanonical whitespace, duplicate keys, unknown schema/version/contract/critical fields and conflicting logical identities. The Node parser uses `BigInt`, UTF-8 key ordering and explicit scalar checks; it is an encoding/digest oracle, not an HNMF semantic authority. Existing golden and shared negative-vector suites remain required independently.

The libFuzzer target now asserts canonical bytes, structural roundtrip and both digest profiles for every accepted V1/V2 input. Compiling this target is not a fuzz campaign, and no long-running fuzz result is claimed by its presence.

`run_mutations.py` evaluates nine targeted source mutants in disposable external Git worktrees: provenance, selected-event, active-node, activation-path, weight-target, threshold-target and topology-node logical identity; the schema-bound digest domain; and the consumer payload-family gate. Each hostile identity fixture preserves full-value canonical ordering so only the reviewed logical-key invariant kills the corresponding mutant. Wire mutants first require the baseline probe to pass, then require the mutant to compile and produce an observably wrong semantic result. The consumer mutant first requires its exact Rust regression to pass on the immutable candidate, then compiles the mutated crate with `--no-run` and counts a kill only when that exact named regression reports `FAILED`. A compiler error, unrelated test failure, crash, timeout, missing anchor or missing output is an invalid experiment, not a killed mutant. The source candidate remains unchanged; only the temporary mutated copy is removed. This is test-sensitivity measurement, not self-modifying qualification or a repair path. The nine experiments do not establish global mutation coverage.

## 6. Performance, traceability and evidence limits

The differential probe includes a bounded timing sample at every declared `MemoryEventV1` collection-count ceiling: 32 spans, 32 cross-modal bindings, 64 semantic keys, 64 provenance entries, 64 causal parents and 64 temporal neighbours. It preserves canonical bytes and both digests and records elapsed time and iteration count without asserting a host-independent performance threshold. It is not a maximum encoded-byte, allocator, long-duration or production-host benchmark; `allocation_measurement` remains null. Existing bounded counting/serialization code and codec tests remain separate obligations.

Run `python3 qualification/cognitive-types-v1/render_traceability.py --check` to verify the generated obligation table and referenced files. For an intentional documentation change, generate to a separate temporary file, inspect it and commit the new projection normally. The verifier never rewrites the candidate to make itself pass.

Outstanding acceptance must be represented explicitly: current exact-source and merge Rust execution, authenticated default-profile composition of all five consumers, authorized compatibility retirement, broad source-mutation coverage, sustained fuzzing, selected-host capacity/allocation measurements and independent acceptance. Preserving those open gates is not a reduction of the target scope. Completion requires their real evidence; source declarations or old run results are not substitutes.
