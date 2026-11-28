# OAuth expected-rejection qualification repair

The Python conformance adapter counted any unsuccessful OAuth login as a passing negative authorization scenario, including failure before callback or issuer validation. An actual invocation of the original function at `dee6b95562226ffd7a5d7d1ef7671130193f9535` reproduced six false qualifications from the existing JSON-RPC error shape for an address-capability rejection.

The repair records the observed login-request or callback-completion stage in a private immutable value. Without a structured semantic rejection reason from the public app-server API, all six expected-rejection cases now fail as unqualified. Unexpected success remains an error. Ordinary login callers retain the existing `(success, error)` return shape and arguments.

This closes the adapter's false-PASS behavior. It does not establish native semantic rejection correctness, proxy support, or an authorization-server origin grant. A transport failure after a real callback also remains unqualified: the stage alone and the upstream fixture's absence-of-token checks are insufficient to prove the reason. No official check, protocol assertion, reviewed baseline, HTTP address guard, feature flag, or dependency policy was weakened.

## Executed validation

| Control | Actual result | Scope |
| --- | --- | --- |
| Exact original adapter reproduction | 6 false qualifications reproduced | Controlled existing RPC error; no native OAuth |
| New stdlib tests | 7/7 passed | Owned loopback HTTP plus controlled RPC notifications |
| Two unchanged original Python suites plus new tests | 102/102 passed: 95 original + 7 new | 30 subtests separately; do not add them to make 132 tests |
| Original `just fmt` | Passed | Two source paths in an explicitly synthetic partial Git inventory |
| Original `just fmt --check` | Passed | Same exact two-path scope |

The pytest command used a private environment with pytest 9.0.3 and its complete active Linux/Python 3.14 dependency closure from the original `sdk/python/uv.lock`. Every wheel was checked against that lock's exact SHA-256. This was not a full SDK installation. All tests ran before final formatting. Production source stayed byte-identical; the new test file changed only formatting, with identical Python AST. No test was rerun after formatting.

The initial formatter scope preflight failed because plain `git status` collapsed a new directory instead of listing individual files. The formatter had not started. Its original output is preserved; the execution preflight was corrected to request all untracked files before running the original commands.

## Hosted baseline

`DEE6_SDK_JOB_141007506966.log.gz` is the complete decoded original job log, copied byte-for-byte from the root audit's evidence. It records actual merge checkout `176c0692f5b7755a747b3fb5b0c20e5046586b88` for source head `dee6...`. The six negative adapter rows were marked PASS, while the entire TypeScript job was already failing: 46 tests passed and one failed. Those six rows alone do not prove each native error cause; the original-function reproduction establishes the unsafe adapter classification mechanism.

`ROOT_DEE6_LOG_ARCHIVE_INDEX.json` is the original five-job provenance index. Only the SDK log is included in this narrow package; the other four entries are external provenance references. This candidate has not yet run hosted CI.

## Files and remaining qualification

`RESULTS.json` binds source hashes, test scopes, commands, and durations. `EVIDENCE_INDEX.json` inventories the raw archive and its individual members. `RAW_EVIDENCE.tar.gz` preserves original source bundles, executable reproduction, untouched test output, formatter output, hashes, and execution scripts.

Native structured rejection reasons, restricted proxy enforcement, and a trusted owner capability for the separate local authorization-server origin remain open. There is no new claim of production OAuth conformance or complete CI success.
