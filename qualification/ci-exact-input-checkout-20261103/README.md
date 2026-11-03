# Fetch only the exact CI comparison inputs

The original `blocking-ci` scope job on `b201d976572f24136a46128169fc627857e45f2b`
was cancelled while `actions/checkout` fetched every historical branch and tag.
It never reached the scope tests or classification. The complete original job
log and its identity are retained in `OBSERVED_CONTROLS.json`. The original
five-minute limit is unchanged.

The workflow now checks out the exact candidate at depth one and invokes the
existing `scripts/hepta_ci_history.py` for the exact event base and head before
classifying a pull request. That helper is already used by the Rust and
architecture workflows. It validates commit identities, fetches missing exact
objects, and fails if an input is unavailable. Fetch authentication stays in
the fetch process environment; checkout still disables persistent credentials.
Push events continue to select the original full scope.

No classifier, dependency graph, test list, fan-in rule, resource threshold or
native acceptance condition changed. The existing 59 scope, dependency and
readiness regressions passed. Only their actual final console output segment
was captured; it is explicitly labelled as incomplete.

`replay_exact_inputs.py` constructs three real local Git histories and shallow
clones. Before the missing base is fetched, the exact comparison fails. After
the existing helper fetches it, the complete-history and shallow results agree
for plain prose, an embedded data change with renamed and deleted documents,
and an unknown shared input requiring the full repository. Unrelated branches
and tags are not fetched. An unavailable exact commit remains a failure.

```sh
python3 qualification/ci-exact-input-checkout-20261103/replay_exact_inputs.py \
  --output /tmp/exact-input-checkout-receipt.json
```

The initial fixture failure is preserved in `INITIAL_PROBE_FAILURE.json` and
`initial_probe.py`. That fixture tried to test object absence using a specific
`git cat-file` lookup, which itself triggered a promisor fetch. The corrected
fixture inventories already present objects without requesting the missing
object. The historical script originally lived under
`qualification/yaml-safe-compatibility/checkout/`; its recorded paths and bytes
are retained as historical evidence, not described as the current executable
probe. The published replay uses its current repository-relative location.

These local controls do not replace the original hosted scope job. Its actual
five-minute execution on the changed commit is a separate required result.
