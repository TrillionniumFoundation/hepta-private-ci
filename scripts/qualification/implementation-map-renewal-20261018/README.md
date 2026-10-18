# Fresh implementation-map navigation observations

This is a preparation tool and review note, not a changed checker or an execution
receipt. No command that changes the Hepta checkout has been executed here.

## Reviewed source and precise failure

Read from local candidate `ce6bbc6f395545fa17f0925c604cbdc65384f73b`:

- Original implementation-map checker blob: `e8ae0fd675b7e3ca2911b80af92cc21021789fbe`.
- Original Lane D semantic checker blob: `75d3d73120bbbcb968d8dbf737940e1f46e1378e`.
- Original Lane D test blob: `ebfe0a79f51138ee3c97c488381b74e249750253`.

The parent independently checked GitHub ancestry. The local checkout is shallow;
missing local commit objects do not establish nonancestry. The preparation tool
requires full local history and repeats the original strict ancestry check.

`migrate()` checks `sourceBase` with `checked_identity()` before preparing any
map. A missing or nonancestor anchor is not `SourceDrift`. Even `exact_blob`
mode preserves that ancestry requirement. Passing `--profile development`
cannot replace the required qualification result.

Five maps have the `e8e81b7d541a81e75635cc1c0a713edaedb999d5` anchor:

- control.engineering
- inference.control
- learning.artifacts
- learning.ledger
- objective.compiler

Fourteen have the `8914a46dfc5984532f03dd2d559bf547ca4f1e69` anchor:

- automation.taskflow
- cognitive.read
- control.runtime
- intelligence.control
- kernel.operations
- knowledge.graph
- learning.operator
- learning.plasticity
- memory.federation
- memory.retrieval
- platform.types
- runtime.codex
- runtime.supervisor
- utility.ndu

The other 21 maps retain valid-anchor handling through the original `migrate`:
auth.authbus, browser.servo, channel.matrix, cognitive.store, cognitive.types,
compact.engine, context.compiler, inference.worker, intuition.policy,
kernel.authority, kernel.evidence, learning.eval, neuron.runtime, platform.wire,
prompt.optimizer, prompt.registry, runtime.agentd, runtime.fleet,
secrets.heptabao, ui.control and ui.native.

## New observation versus historical evidence

The 19 originals all have false standard execution/production/acceptance flags.
Their exact Git blobs remain authoritative for what those records said; retain
the original bytes, Git blob identity, SHA-256, sourceBase, and actual original
checker nonancestor failure. Do not call a new source observation a successful
migration of the rejected anchor.

For the new records, the tool uses the original `migrate_map()` only as a field
renderer, and the original source, binding, inventory and blob validators. It
keeps operation names, owners, sources, tests, delegates and existing exact-blob
mode, and binds the final clean code's actual current paths/objects under the
existing stronger `candidate_or_exact_observation_v1` policy.

Old top-level metadata that labels prior commits as current source or an old head
attestation is preserved in the exact archived blob and referenced as historical
metadata. It is not edited to pretend the old run used the new commit. Permanent
integrationBaseline values remain historical baseline values. Currentness is
expressed by the new `sourceBase`/`observedAtHead` and exact source objects.
The old objective-compiler policy text that referred to the removed legacy
`exactSourceCandidate`/`productCompositionSourceCandidate` fields is archived
with those fields; the unchanged checker and its actual qualification policy
remain intact.

### utility.ndu needs explicit treatment

Its old `claimBoundary.requestLocalReadOnlyProductExecutionProved` is true.
That specialized name is absent from the implementation-map checker's standard
`EXECUTION_CLAIMS`; treating the row as having no execution declaration would
transfer an old assertion accidentally. The fresh navigation record sets this
current-execution flag false and points to the byte-exact old record retaining
the true declaration. This does not establish whether the historical assertion
was independently proved, and it grants no current product execution.
The retained `productCallerProfiles.requestLocalReadOnly.state = established`
describes its source call chain, not a new executed product observation. The new
observation explicitly limits itself to source paths, exact Git objects and
source call-composition navigation. Source-implementation Booleans such as
`productionWriterSourceImplemented` also remain source claims; their corresponding
activation and product-execution claims remain false.

The original Lane D checker already accepts a false read-only execution claim.
Its existing negative test happens to load the current real map and assume that
flag is true before mutating the caller. `lane_d_fixture.patch` changes only that
test's local copy: it explicitly sets the positive claim, validates the real
caller, then retains the missing-caller rejection. The checker and negative
assertion remain unchanged; the committed map stays false.

## Owner execution order

1. Finish and commit actual implementation code and the test-only Lane D fixture
   adjustment. Use a fully fetched checkout. Retain the original full failure
   log when available; per-anchor records in the new bundle have a narrower
   explicitly stated scope. The two side-branch anchor commits must actually be
   available as well as the final candidate history; fetching only main need
   not supply nonancestor side-branch objects. Missing objects cause refusal.
2. Run the original `migrate --module ...` for the 21 valid-anchor modules and
   commit its real changes. If its original execution or source checks reject,
   investigate the rejection without lowering the claim or checker.
3. Prepare the 19 new observations at that exact clean HEAD:

   ```sh
   python3 /path/to/prepare_navigation_observation.py \
     --repo /path/to/full-history/hepta-private-ci \
     --expected-head <literal-final-clean-source-SHA> \
     --out /path/to/a-new-external-directory \
     --retained-prefix qualification/implementation-map-renewal-20261018
   ```

4. Review `PAYLOAD_SHA256.json`, every new map and the retained original/failure
   records under `payload/`. The tool never copies these into the checkout.
   The owner can apply that reviewed payload, run the original
   `sync-plasticity-status` for its existing generated projections, then commit.
5. Run the unmodified complete `verify --profile qualification --expected-sha
   <new-commit> --expected-tree <new-tree>` and the original full source/native
   gates on the actual final source. The prepared source anchor is an ancestor
   of this metadata commit, avoiding cryptographic self-reference. Any mapped
   source change after preparation must use the original migration/review path.

No old producer version, native execution log, GitHub run, acceptance flag or
receipt is relabeled. The archived failure remains a failure on its recorded
candidate. `PREPARED` means proposed navigation bytes passed individual original
source checks; it does not mean the whole repository verified or executed.

### Copyable original migration selection

Run this from the final clean repository after the implementation and test
fixture commit, following its existing project preflight. It invokes the
unchanged owner for the exact 21 valid-anchor maps only:

```sh
python3 scripts/hepta-implementation-maps.py migrate \
  --module auth.authbus --module browser.servo --module channel.matrix \
  --module cognitive.store --module cognitive.types --module compact.engine \
  --module context.compiler --module inference.worker --module intuition.policy \
  --module kernel.authority --module kernel.evidence --module learning.eval \
  --module neuron.runtime --module platform.wire --module prompt.optimizer \
  --module prompt.registry --module runtime.agentd --module runtime.fleet \
  --module secrets.heptabao --module ui.control --module ui.native
git diff --check
```

Review and commit those actual metadata changes before running `prepare`.
For the prepared output, this read-only integrity check verifies every payload
byte and all 19 retained original/failure pairs. Pass the actual output directory
as the script's single argument; the variable below is only a path selection.
It is not a substitute for the original full qualification checker.

```sh
hepta_navigation_output=/path/to/a-new-external-directory
python3 - "$hepta_navigation_output" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "PAYLOAD_SHA256.json").read_text())
payload = root / "payload"
assert set(manifest) == {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
for relative, expected in manifest.items():
    assert hashlib.sha256((payload / relative).read_bytes()).hexdigest() == expected, relative
report, = [json.loads(p.read_text()) for p in payload.glob("qualification/*/OBSERVATION.json")]
assert report["status"] == "PREPARED" and len(report["modules"]) == 19
assert report["nativeExecutionPerformed"] is False
assert report["historicalExecutionReceiptsRebound"] is False
assert len({entry["module"] for entry in report["modules"]}) == 19
for entry in report["modules"]:
    retained = entry["retained"]
    raw = (payload / retained["archivedBlobPath"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == retained["sha256"]
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == retained["gitBlob"]
    original = json.loads(raw)
    assert original["module"] == entry["module"]
    assert original["sourceBase"] == retained["sourceBase"]
    failed = (payload / retained["strictAnchorFailurePath"]).read_bytes()
    assert hashlib.sha256(failed).hexdigest() == retained["strictAnchorFailureSha256"]
    failure = json.loads(failed)
    assert failure["returncode"] == 1
    assert failure["sourceBase"] == original["sourceBase"]
    assert failure["candidate"] == report["candidate"]
    assert failure["command"][-4:] == ["merge-base", "--is-ancestor", original["sourceBase"]["commit"], report["candidate"]["commit"]]
    new_raw = (payload / retained["mapPath"]).read_bytes()
    assert hashlib.sha256(new_raw).hexdigest() == entry["newMapSha256"]
    fresh = json.loads(new_raw)
    assert fresh["sourceBase"] == report["candidate"]
    for claim in (fresh, fresh.get("claimBoundary", {}), fresh.get("completion", {})):
        for name in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"):
            assert claim.get(name, False) is False, (entry["module"], name)
    if entry["module"] == "utility.ndu":
        assert original["claimBoundary"]["requestLocalReadOnlyProductExecutionProved"] is True
        assert fresh["claimBoundary"]["requestLocalReadOnlyProductExecutionProved"] is False
        assert entry["claimChanges"] == fresh["sourceNavigationObservation"]["claimChanges"]
print("19 original blobs and original ancestry failures retained; prepared navigation only")
PY
```

Only after reviewing the complete output should the owner copy its payload into
the repository, run `python3 scripts/hepta-implementation-maps.py sync-plasticity-status`,
and commit. A failed or partial preparation is not an applicable payload: retain
its error/output, keep the original maps unchanged, and resolve the actual failed
source check before preparing into a new output directory.

## Local validation of this preparation tool

`test_prepare_navigation_observation.py` includes five controls in a small isolated
Git repository using unmodified copies of the original checker and source-root
resolver: real nonancestor versus valid/missing identities; exact blob newline
retention; no generic positive-execution downgrade; and specialized historical
read-only declaration retention with false fresh execution; and wrong-module
refusal before the original field renderer can rename it. `git apply --check`
also accepted the test-only patch. The tool's full preparation command has not
been run on the shared Hepta checkout.
