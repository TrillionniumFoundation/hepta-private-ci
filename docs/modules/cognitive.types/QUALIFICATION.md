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

### 4.1 Closed command capture retained by check-plan version 4

The existing `run_check` entrypoint now delegates process and log capture to `command_process.py`; native, consumer and owner commands, as well as mutation builds and exact-test experiments, retain that same entrypoint. The capture change itself does not alter package selection, lint strictness or candidate identity; the additive resource commands in version 4 are described below. It repairs an observed counterexample: a parent exited zero, the old runner sealed an empty passing log, and its child subsequently appended 14 bytes, invalidating the recorded digest.

The parent exclusively creates and owns each log file; children receive a pipe instead of the writable log descriptor. Existing files and symlink aliases reject rather than overwrite. The selected POSIX runner uses a monotonic deadline, reads at most 64 KiB per chunk, retains at most 64 MiB per command and allows five seconds for leader cleanup after termination. Exceeding the log limit retains a bounded diagnostic prefix with `log_complete: false`; it is `infrastructure_invalid`, never a truncated pass or a killed semantic mutant. Missing programs, deadlines, signals and residual process groups also cannot pass. A properly waited child and an exactly-at-limit complete log remain valid observations.

Every command records `capture_version`, `log_complete`, `process_group_closed`, `log_bytes` and `log_limit_bytes`. Both receipt sealing and six-artifact verification require strictly typed completion facts, the reviewed limit and exact correspondence with the inventoried log bytes and digest. Check-plan version 4 retains this capture contract and rejects earlier plans as current evidence; older evidence remains historical and is not rewritten. The evidence schema and frozen cognitive wire/digest profiles are unchanged.

This is bounded pipe capture and owned-process-group cleanup, not an OS sandbox or a proof that every process on the host has stopped. Processes that create a separate session/group, including independently supervised nested commands, require host-level containment for whole-tree cancellation; file-system mutation by an escaped or unrelated process is not prevented by this helper. Unresolved cleanup remains nonpassing. Current owner authentication, revocation and final-use checks are not cached or supplied by the runner.

The focused regression entrypoint is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s qualification/cognitive-types-v1 -p 'test_*.py'
```

For development without the complete repository, the narrower `test_command_process`, `test_run_qualification` and `test_verify_receipts` modules can be run explicitly from that directory. Those process/fixture tests are not Rust, cross-language, source-mutation, authenticated product or selected-host capacity qualification. The full command plan and both fixed candidate trees remain mandatory for module acceptance.

### 4.2 Required byte-boundary resource observations in check-plan version 4

The existing native group retains every debug probe, differential, mutation, vector, package and lint check. It additionally builds `canonical_probe` with `--release --locked` and runs `resource_profile.py --samples 3 --heap`. Both exact-head and synthetic-merge native receipts must contain `resources/resource-receipt.json`; the unchanged recursive evidence inventory binds the raw time/DHAT files and every bounded probe observation, including refusals. Missing tools, malformed or incomplete measurements, changed executable/source identity, omitted commands and resealed missing files fail qualification. The workflow installs GNU time and Valgrind only for the native group and records their observed versions. Trigger paths now include the direct `hepta-types` dependency and both protocol registries.

`resource_workloads.py` derives inputs from the existing maximum-count MemoryEvent fixture. It fills only registered bounded identifiers, cross-modal references and AST/JSON-pointer paths. It tests payload sizes 262143, 262144 and 262145 separately from the 263168-byte envelope ceiling and its one-byte excess. Near-limit malformed JSON and conflicting provenance identities must produce their exact structured refusal classes. These Python builders do not establish native validity: the actual production decoder remains the authority for structural acceptance, and the responsible owner remains the authority for use.

Each case has three native-process observations and one separately instrumented heap observation. Successful native observations retain 256 decode/encode iterations; the heap observation uses one iteration. A rejected input performs one decode per process, not 256 hidden retries. GNU time records whole-process user/system CPU at its reported hundredth-second precision and maximum resident set, including startup. A zero rounded CPU value is not zero cost. DHAT records allocated bytes/blocks, global-peak live bytes/blocks and exit-live bytes/blocks; global peak sums `gb` contributions rather than unrelated per-site maxima. Instrumented measurements are not native latency. The script preserves raw files, strict integer counters, bounded reads, actual exit outcomes, binary/workload SHA-256 identities and the selected host description. It enforces no invented latency or memory threshold and grants no product acceptance.

The existing bounded `probe_execution.py` also rejects a leader that exits while redirected descendants remain. Closing the output pipes is not proof of complete process-group termination. A synthetic Python counterexample reproduced the old false pass; the new regression requires `infrastructure_invalid`. This remains process-group management, not containment of deliberately escaped sessions or unrelated host processes.

The local continuation executed 39 tests in `test_verify_receipts` and `test_resource_profile` against SHA-verified source copies. These use synthetic Git matrices/processes and profiler fixtures; they are not Rust or DHAT execution on the actual codec. A separate Python check preserved the retained MemoryEvent golden digest and constructed all seven byte-boundary inputs. Native compilation, all six real candidate groups, actual DHAT observations, long-duration fuzzing and authenticated product cutover still require their own execution evidence.

## 5. Cross-language, hostile-input and source-mutation evidence

`examples/canonical_probe.rs` invokes the actual 16 registered production decoders; it defines no replacement protocols or authenticated owner. On success it checks exact canonical roundtrip and emits both digest profiles. A structural rejection is a machine-readable violation with process exit 2. Crashes, missing tools and malformed output are not accepted as negative-test successes.

`quality_checks.py` consumes the retained 12 V1 and four V2 golden payloads, checks their frozen digests, and compares actual Rust output with independent Python and Node digest calculations. Additional cases cover full-width unsigned integers, Unicode scalar preservation, JSON pointer escapes, noncanonical whitespace, duplicate keys, unknown schema/version/contract/critical fields and conflicting logical identities. The Node parser uses `BigInt`, UTF-8 key ordering and explicit scalar checks; it is an encoding/digest oracle, not an HNMF semantic authority. Existing golden and shared negative-vector suites remain required independently.

The libFuzzer target now asserts canonical bytes, structural roundtrip and both digest profiles for every accepted V1/V2 input. Compiling this target is not a fuzz campaign, and no long-running fuzz result is claimed by its presence.

`run_mutations.py` evaluates nine targeted source mutants in disposable external Git worktrees: provenance, selected-event, active-node, activation-path, weight-target, threshold-target and topology-node logical identity; the schema-bound digest domain; and the consumer payload-family gate. Each hostile identity fixture preserves full-value canonical ordering so only the reviewed logical-key invariant kills the corresponding mutant. Wire mutants first require the baseline probe to pass, then require the mutant to compile and produce an observably wrong semantic result. The consumer mutant first requires its exact Rust regression to pass on the immutable candidate, then compiles the mutated crate with `--no-run` and counts a kill only when that exact named regression reports `FAILED`. A compiler error, unrelated test failure, crash, timeout, missing anchor or missing output is an invalid experiment, not a killed mutant. The source candidate remains unchanged; only the temporary mutated copy is removed. This is test-sensitivity measurement, not self-modifying qualification or a repair path. The nine experiments do not establish global mutation coverage.

## 6. Performance, traceability and evidence limits

The differential probe includes a bounded timing sample at every declared `MemoryEventV1` collection-count ceiling: 32 spans, 32 cross-modal bindings, 64 semantic keys, 64 provenance entries, 64 causal parents and 64 temporal neighbours. It preserves canonical bytes and both digests and records elapsed time and iteration count without asserting a host-independent performance threshold. It is not a maximum encoded-byte, allocator, long-duration or production-host benchmark; `allocation_measurement` remains null. Existing bounded counting/serialization code and codec tests remain separate obligations.

### 6.1 Borrowed record work and typed consumer refusals

`MemoryRecord::record_digest` now sorts references rather than cloning citation values and their identifiers. Existing citation/record uniqueness checks also borrow their keys. Full-value ordering, logical uniqueness, raw-DTO digest behavior and all frozen byte framing are unchanged; no cross-request cache or authorization result is introduced. `record_digest_reuse_tests.rs` retains an independent old concatenating implementation and checks ordering, boundaries, duplicate identities and stale snapshots. An independent Python framing/order check executed 288 cases locally; it does not execute the Rust implementation or establish a measured speedup.

The shared consumer constructor now preserves codec failures in a sealed `CanonicalContractFailureV1`, surfaced as `CanonicalContractTyped`, rather than erasing new failures into strings. Its structured category, field and payload-free message come from the existing wire error projection. The historical `CanonicalContract(String)` remains readable and generically redacted, never parsed for authority or error categories. This is an additive Rust error variant, not a new wire schema; downstream exhaustive matches must be compiled on the current candidate. `consumer_typed_error_tests.rs` covers category/privacy preservation and rejection followed by legitimate use through the public recall constructor. Native execution of these additions was not available in the local continuation.

Run `python3 qualification/cognitive-types-v1/render_traceability.py --check` to verify the generated obligation table and referenced files. For an intentional documentation change, generate to a separate temporary file, inspect it and commit the new projection normally. The verifier never rewrites the candidate to make itself pass.

Outstanding acceptance must be represented explicitly: current exact-source and merge Rust execution, authenticated default-profile composition of all five consumers, authorized compatibility retirement, broad source-mutation coverage, sustained fuzzing, selected-host capacity/allocation measurements and independent acceptance. Preserving those open gates is not a reduction of the target scope. Completion requires their real evidence; source declarations or old run results are not substitutes.

## 7. Adversarial review of the 2026-09-30 candidate

The reviewed source was `682d1f5317bf00e666ff822709c244e6958f6c1c`, the head of the existing draft PR #1134, against main `a126987b84737dbc2ee2592442a314117bddb4a2`. Earlier main-only identity and pointer findings are already repaired in that candidate and are not new defects.

The review found six unregistered Rust test modules: contract, consumer, hardening, Shared Experience, Shared Experience context and borrowed record digest regressions. They are now registered in the crate root. A successful exact-filter command with zero executed tests previously let the consumer-family mutant survive. Mutation evidence now requires the named successful test and a one-test passing summary; zero tests and unrelated tests are infrastructure-invalid. The schema-bound-domain mutant now changes the production legacy codec used by the probe, rather than an unused facade constant. The cross-language verifier follows the registered split codec and base fixture and rejects a disconnected test harness.

Native learning serialization previously allocated a complete JSON buffer before enforcing its maximum. It now shares the bounded counting writer. Counted-sequence and escaped-Unicode regressions check early termination and exact byte boundaries. LimitExceeded.actual is a witnessed lower bound (maximum + 1), not a measurement of an intentionally unmaterialized remainder.

The review also restores Rust formatting, updates source-export traceability to the existing immutable SOURCE_SHA and PR-head concurrency expressions, removes an unnecessary test clone, and repairs the constant-size claims-frame iteration in the shared authority dependency. The existing divisibility and bounded-read checks remain in force. A narrow allowance on the deprecated NDU compatibility re-export preserves warnings at actual downstream uses while avoiding an error merely for retaining that export.

The local validation commands are:

```sh
cd codex-rs
just test --locked -p codex-hepta-cognitive-types
cargo clippy --locked -p codex-hepta-cognitive-types -p codex-hepta-cognitive-read -p codex-hepta-cognitive-store -p codex-hepta-memory-retrieval -p codex-hepta-compact-engine -p codex-hepta-intelligence --all-targets -- -D warnings
just test --locked -p codex-hepta-contracts -p codex-hepta-cognitive-read -p codex-hepta-cognitive-store -p codex-hepta-memory-retrieval -p codex-hepta-compact-engine -p codex-hepta-intelligence
cd ..
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qualification/cognitive-types-v1 -p 'test_*.py'
python3 qualification/cognitive-types-v1/verify_vectors.py
```

Local command outcomes are review evidence, not replacement immutable hosted receipts. The observed hosted runs on the reviewed source included failed native qualification and failed store/control depth jobs. Development-docs qualification also reported stale implementation-map observations in other modules. Old PR prose saying that an earlier candidate is pending cannot establish the current source's status. Required source/base/host receipts, sustained fuzz campaigns, physical owner-authenticated final use, compatibility retirement and independent acceptance remain separate gates. This repair does not set any of those gates to true.
