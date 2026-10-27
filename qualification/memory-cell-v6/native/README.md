# Native memory readout boundary

The qualification caller executes the repository's Rust contracts, retrieval
revalidation and context compiler on a readout produced by the Python router and
three-cell runtime. The returned value stays `mixed` or `model_prediction` where
appropriate and enters the context compiler only as `UntrustedEvidence`.

`make_fixture.py` writes four public synthetic entities to the SQLite source
owner, actually trains the semantic and procedure cells, loads an identity-bound
trained router and evaluates one `apply` request. The recorded example produces
`41 * 7 + 3 = 290`. It then performs a real source revocation and checks the Python
runtime refuses the stale bundle. Both owner frontiers are exported for Rust.

`bridge.rs` decodes the typed request and readout, checks their query, generation,
snapshot and execution budgets, revalidates every dependency against the owner
export, and calls `hepta-context-compiler::compile`. The result must contain one
untrusted evidence item, no trusted instructions and no granted authority. The
revoked owner export must fail before compilation.

## Reproduce

Use a trained router's recorded manifest digest, its matching pinned encoder,
and fresh output directories. Run `make_fixture.py --help` for the three required
router inputs. Then run:

```sh
python qualification/memory-cell-v6/native/qualify.py \
  --output /absolute/path/to/fresh-native-leaf \
  --tool-root /absolute/path/to/native-tools \
  --fixture-dir /absolute/path/to/generated-fixture
```

The script copies six complete crate source directories into a separate leaf
workspace. It retains the workspace dependency declarations and lints, seeds the
leaf lock from the repository lock and verifies that every resolved external
package has the same version, source and checksum as a repository lock entry.
Only the unused dev dependencies of the transitive `hepta-contracts` crate are
removed from the leaf manifest. Nextest overrides for packages absent from this
declared leaf are removed from its generated configuration; selected tests and
global timeout/retry settings remain.

The script calls the original repository `just test` recipe with `--locked` and
the leaf manifest, then builds and executes the native bridge. Every command,
exit status, duration and log hash is recorded in `NATIVE-QUALIFICATION.json`,
along with copied source hashes and the resulting binary hash. After all tests
and executable checks, run the same script with `--fix-only` and the existing
output directory to invoke the repository's required `just fix` step. Do not
rerun tests after that step or the final repository formatting pass.

## Observed result and limits

The recorded run passed 127 tests across cognitive types, memory retrieval and
context compiler, including all seven added memory-cell tests. Two pre-existing
target-host structural/latency probes remained ignored by their existing
annotations. `just fix` exited successfully and changed no Rust source; existing
test code emitted `expect`/`unwrap` lint warnings, so this is not a claim that the
entire leaf is lint-clean.

The successful bridge returned value `290`, retained `mixed`, admitted only
`memory:query:native-fixture` as untrusted evidence, and granted no authority. The
second executable call rejected a revoked source with exit status 1.

This is a leaf qualification, not a full product build. The owner export is a
public synthetic fixture, not a live authenticated owner or a production
revocation adapter. The compiler receives digests through its V1 API; this does
not claim provider delivery or tokenizer certification. Token cost is a byte
upper bound for the fixture. The full organ/TaskFlow product caller still needs
to supply the live owner implementation and actual admission/delivery lifecycle.
The source hashes bind the bytes tested before the required final formatter.
