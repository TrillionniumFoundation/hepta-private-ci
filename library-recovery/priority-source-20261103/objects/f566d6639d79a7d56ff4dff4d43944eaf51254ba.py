from pathlib import Path
import difflib
R=Path(__file__).parent;C=R/'current';B=R/'base'
p='docs/modules/kernel.operations/TECHNICAL.md';t='qualification/module-execution-dossiers/test_lane_a_foundation.py'
before={p:(B/p).read_text(),t:(B/t).read_text()};s=before[p]
s=s.replace('Canonical exact source identity is recorded by `IMPLEMENTATION_MAP.json` with `sourceIdentityPolicy=path_blob_manifest_v1`. The verifier resolves every mapped path through `git rev-parse HEAD:<path>`; a tracked map therefore does not need to contain its own future HEAD/tree hash.', 'Canonical source identity is recorded by `IMPLEMENTATION_MAP.json` with `sourceIdentityPolicy=candidate_or_exact_observation_v1`. Its separate `exactSourceEvidence.kind=path_blob_manifest_v1` records mapped file blob identities. The verifier checks candidate or exact historical observations, tracked evidence paths and mapped blobs; a tracked map does not contain its own future HEAD/tree hash. These are distinct metadata fields, and source changes still require current candidate verification rather than inheriting an older observation.')
s=s.replace('- Exact mapped source identity is verified through `path_blob_manifest_v1`.', '- The map declares `sourceIdentityPolicy=candidate_or_exact_observation_v1` and separately records `exactSourceEvidence.kind=path_blob_manifest_v1`; both source-identity and blob-manifest checks must pass for the actual candidate.')
s=s.replace('- `productionImplementation=true` means repository source implementation exists; it does not mean product execution, activation, acceptance or release.', '- The current map retains `productionImplementation=false`. The source implementations described here do not raise that claim or establish product execution, activation, acceptance or release.')
assert s!=before[p];(C/p).write_text(s)
newtest='''    def test_operations_guide_matches_identity_metadata(self) -> None:
        metadata = verify.read_json(
            ROOT / "docs/modules/kernel.operations/IMPLEMENTATION_MAP.json"
        )
        guide = (ROOT / "docs/modules/kernel.operations/TECHNICAL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f"`sourceIdentityPolicy={metadata['sourceIdentityPolicy']}`", guide
        )
        self.assertIn(
            f"`exactSourceEvidence.kind={metadata['exactSourceEvidence']['kind']}`",
            guide,
        )
        self.assertIn(
            f"`productionImplementation={str(metadata['productionImplementation']).lower()}`",
            guide,
        )

'''
s=before[t];needle='    def test_native_observation_manifest_binds_current_candidate_blobs(self) -> None:\n';assert needle in s;s=s.replace(needle,newtest+needle);(C/t).write_text(s)
text=''
for path,old in before.items():text+=''.join(difflib.unified_diff(old.splitlines(True),(C/path).read_text().splitlines(True),fromfile='a/'+path,tofile='b/'+path))
(R/'patches/05-identity-docs.patch').write_text(text)

# Optional one-level additional surfaces retain machine-readable IDs while
# preserving the existing one-primary-entry-per-module index contract.
import json
registry_path='docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json'
core_path='scripts/lane_a_foundation_core.py'
lib_path='scripts/lane_a_foundation_lib.py'
readme_path='docs/lane-a-foundation/README.md'
for path in (registry_path,core_path,lib_path,readme_path):before[path]=(B/path).read_text()
registry=json.loads(before[registry_path]);rows=registry['protocols'];ops=[row for row in rows if row['module']=='kernel.operations'];assert len(ops)==2
primary,product=ops
assert primary['protocolId']=='hepta.kernel.operations.durable-ledger-outbox.v1'
assert product['protocolId']=='hepta.kernel.operations.durable-owner.v1'
primary['additionalProtocols']=[product]
registry['protocols']=[row for row in rows if row is not product]
(C/registry_path).write_text(json.dumps(registry,indent=2)+'\n')
validation='''def validate_protocol_registry(value: dict[str, Any], root: Path = ROOT) -> None:
    """Validate one module entry plus optional same-owner executable surfaces."""
    rows = value.get("protocols")
    if (
        set(value) != {"schemaVersion", "lane", "role", "authority", "protocols"}
        or value.get("schemaVersion") != 1
        or value.get("lane") != "LANE-A-FOUNDATION"
        or value.get("role") != "current_executable_protocol_index"
        or value.get("authority") != "none"
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
        or [row.get("module") for row in rows] != EXPECTED_MODULES
    ):
        raise VerificationError("protocol registry header/module set mismatch")
    identities: set[str] = set()
    for row in rows:
        additional = row.get("additionalProtocols", [])
        if not isinstance(additional, list):
            raise VerificationError("additional protocols must be a list")
        for surface in [row, *additional]:
            if (
                not isinstance(surface, dict)
                or set(surface).difference({
                    "protocolId", "module", "kind", "source", "invariants",
                    "legacyProtocolId", "additionalProtocols",
                })
                or surface.get("module") != row["module"]
                or (surface is not row and "additionalProtocols" in surface)
                or not isinstance(surface.get("kind"), str)
                or not surface["kind"]
            ):
                raise VerificationError("invalid additional protocol owner/shape")
            for field in ("protocolId", "legacyProtocolId"):
                if field == "legacyProtocolId" and field not in surface:
                    continue
                identity = surface.get(field)
                if (
                    not isinstance(identity, str)
                    or not identity.startswith("hepta.")
                    or identity in identities
                ):
                    raise VerificationError("invalid/duplicate protocol identity")
                identities.add(identity)
            for field in ("source", "invariants"):
                items = surface.get(field)
                if not isinstance(items, list) or not items or any(
                    not isinstance(item, str) or not item.strip() for item in items
                ):
                    raise VerificationError(f"protocol {field} must be nonempty")
                if field == "source":
                    for item in items:
                        source = Path(item)
                        if (
                            chr(0) in item or chr(92) in item
                            or not source.parts
                            or source.is_absolute() or ".." in source.parts
                            or source.as_posix() != item
                            or not (root / source).resolve().is_relative_to(root.resolve())
                            or not (root / source).exists()
                        ):
                            raise VerificationError("invalid/unavailable protocol source path")


'''
s=before[core_path];needle='def validate_capability_map(\n';assert needle in s;s=s.replace(needle,validation+needle,1);(C/core_path).write_text(s)
s=before[lib_path];needle='    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")\n';assert needle in s;s=s.replace(needle,'    validate_protocol_registry(\n        read_json(root / "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json"), root\n    )\n'+needle,1);(C/lib_path).write_text(s)
s=before[readme_path];needle='## Internal bloc';i=s.index(needle);s=s[:i]+'''### Multiple executable surfaces in one module

`PROTOCOL_REGISTRY_V1.json` keeps one primary entry per Lane A module.
The optional `additionalProtocols` array contains one level of complete,
same-module protocol records, retaining each `protocolId`, source list and
invariants. Primary and legacy identifiers are unchanged; readers enumerating
all current surfaces include the primary record and its additional records.
Identifiers remain unique across current and legacy records, and nested
additional records cannot introduce another owner or another nesting level.

For `kernel.operations`, `hepta.kernel.operations.durable-ledger-outbox.v1`
continues to describe the standalone qualification owner and retains the
`hepta.kernel.operations.reference-model.v1` legacy identifier. Its additional
`hepta.kernel.operations.durable-owner.v1` record describes the CognitiveStore
product owner. These are distinct persistence roles, not interchangeable wire
identities or permission to dual-write one logical operation. Indexing a
surface grants no product activation, acceptance or release authority.

'''+s[i:];(C/readme_path).write_text(s)
s=(C/t).read_text();needle='    def test_operations_guide_matches_identity_metadata(self) -> None:\n';tests='''    def test_protocol_registry_preserves_additional_operations_surface(self) -> None:
        registry = verify.read_json(
            ROOT / "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json"
        )
        verify.validate_protocol_registry(registry)
        primary = registry["protocols"][3]
        self.assertEqual(
            primary["protocolId"], "hepta.kernel.operations.durable-ledger-outbox.v1"
        )
        self.assertEqual(
            primary["legacyProtocolId"], "hepta.kernel.operations.reference-model.v1"
        )
        self.assertEqual(len(primary["additionalProtocols"]), 1)
        product = primary["additionalProtocols"][0]
        self.assertEqual(
            product["protocolId"], "hepta.kernel.operations.durable-owner.v1"
        )
        self.assertIn("codex-rs/hepta-operations/src/durable_store.rs", primary["source"])
        self.assertIn("codex-rs/hepta-memory/src/production_writer.rs", product["source"])
        by_id = {
            surface["protocolId"]: surface
            for row in registry["protocols"]
            for surface in [row, *row.get("additionalProtocols", [])]
        }
        self.assertEqual(by_id[primary["protocolId"]], primary)
        self.assertEqual(by_id[product["protocolId"]], product)
        primary_only = deepcopy(registry)
        primary_only["protocols"][3].pop("additionalProtocols")
        verify.validate_protocol_registry(primary_only)

    def test_protocol_registry_rejects_duplicate_ids_foreign_owners_and_nested_surfaces(self) -> None:
        registry = verify.read_json(
            ROOT / "docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json"
        )
        mutations = (
            lambda value: value["protocols"].append(deepcopy(value["protocols"][3])),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "protocolId", value["protocols"][3]["protocolId"]
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "module", "kernel.authority"
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "additionalProtocols", []
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "source", []
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "invariants", []
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "source", ["../outside.rs"]
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "source", ["missing-source.rs"]
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "source", ["."]
            ),
            lambda value: value["protocols"][3]["additionalProtocols"].append("malformed"),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "activation", True
            ),
            lambda value: value["protocols"][3]["additionalProtocols"][0].__setitem__(
                "legacyProtocolId", value["protocols"][3]["legacyProtocolId"]
            ),
        )
        for mutation in mutations:
            invalid = deepcopy(registry)
            mutation(invalid)
            with self.subTest(mutation=mutation), self.assertRaises(verify.VerificationError):
                verify.validate_protocol_registry(invalid)

'''
assert needle in s;s=s.replace(needle,tests+needle,1);(C/t).write_text(s)
text=''
for path,old in before.items():text+=''.join(difflib.unified_diff(old.splitlines(True),(C/path).read_text().splitlines(True),fromfile='a/'+path,tofile='b/'+path))
(R/'patches/05-identity-docs.patch').unlink()
(R/'patches/05-protocol-metadata.patch').write_text(text)
print('Consolidated structured product surface without removing any original identity/source/invariant')
