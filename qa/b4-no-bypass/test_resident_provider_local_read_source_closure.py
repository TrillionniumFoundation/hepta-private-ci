"""Reject source changes that bypass original provider/readback boundaries.

These are source mechanisms, not authorization, a deployed owner, or proof of
a completed ordinary learning task. Exact scope data must follow actual final
formatting before a qualified source snapshot can be frozen.
"""

from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
SPEC = importlib.util.spec_from_file_location(
    "provider_original_scope_helpers",
    ROOT / "qa/b4-no-bypass/test_evaluated_published_read_source_closure.py",
)
assert SPEC is not None and SPEC.loader is not None
SCOPES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCOPES
SPEC.loader.exec_module(SCOPES)
PROOF = SCOPES.PROOF

# Exact prepared data; final formatting must be frozen again.
CONTRACT_PATH = ROOT / "qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json"
CONTRACT_BYTES = CONTRACT_PATH.read_bytes()
if hashlib.sha256(CONTRACT_BYTES).hexdigest() != 'bd720ff5576f1a02f6dc6c67dff9a286befa353a626a22a37b4c1d5bfa11cae7':
    raise PROOF.VerificationFailure("exact reviewed provider source contract required")
CONTRACT = json.loads(CONTRACT_BYTES)


def require(value, reason):
    if not value:
        raise PROOF.VerificationFailure(reason)


def active_source(source):
    """Retain original literals, blank exactly the original test-only items.

The original predicate decides which attributes cannot hold in production.
The final equality checks that this literal-preserving projection has exactly
the same production code as the unchanged original scanner.
"""
    plain = PROOF._strip_rust_non_code(source)
    code = PROOF._strip_cfg_test_items(plain)
    result = list(source)
    index = 0
    while True:
        start = plain.find("#[", index)
        if start < 0:
            break
        attr_end = PROOF._matching_delimiter(plain, start + 1, "[", "]")
        require(attr_end is not None, "complete original cfg attribute")
        attribute = plain[start:attr_end + 1]
        cfg = re.fullmatch(r"#\[\s*cfg\s*\((.*)\)\s*\]", attribute, re.DOTALL)
        if cfg is None or PROOF._cfg_without_test(cfg.group(1)) is not False:
            index = attr_end + 1
            continue
        cursor = attr_end + 1
        while True:
            cursor = PROOF._skip_space(plain, cursor)
            if not plain.startswith("#[", cursor):
                break
            extra_end = PROOF._matching_delimiter(plain, cursor + 1, "[", "]")
            require(extra_end is not None, "complete original extra attribute")
            cursor = extra_end + 1
        end = PROOF._rust_item_end(plain, cursor)
        require(end is not None, "complete original test-only item")
        for offset in range(start, end + 1):
            if result[offset] != "\n":
                result[offset] = " "
        index = end + 1
    literal_source = "".join(result)
    require(PROOF._strip_rust_non_code(literal_source) == code,
            "literal projection must equal original production mask")
    return code, literal_source


def actual_scope(code, selector):
    kind = selector["kind"]
    if kind == "root_type":
        span = SCOPES.ordinary_select_scope(PROOF, code, selector)
        return span["start"], span["end"]
    if kind == "root_container":
        found = [item for item in SCOPES.ordinary_root_containers(PROOF, code)
                 if item["header"] == selector["header"]]
        anchor = selector.get("anchor")
        if anchor is not None:
            pattern = r"\bfn\s+" + re.escape(anchor) + r"\s*(?=[(<])"
            found = [item for item in found
                     if len(re.findall(pattern, code[item["opening"] + 1:item["end"] - 1])) == 1]
        require(len(found) == 1, "one actual root impl/trait with the fixed anchor")
        return found[0]["start"], found[0]["end"]
    if kind == "root_function":
        found = [match for match in re.finditer(
            r"\bfn\s+" + re.escape(selector["name"]) + r"\s*(?=[(<])", code)
            if SCOPES.ordinary_depth_at(code, match.start()) == (0, 0, 0)]
        require(len(found) == 1, "one actual module function, not a trait or nested decoy")
        end = PROOF._rust_item_end(code, found[0].start())
        require(end is not None and code[end] == "}", "complete module function body")
        start = code.rfind("\n", 0, found[0].start()) + 1
        while code[start].isspace():
            start += 1
        return start, end + 1
    if kind == "root_named_item":
        pattern = (r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?"
                   + re.escape(selector["item_kind"]) + r"\s+"
                   + re.escape(selector["name"]) + r"\b")
        found = []
        for match in re.finditer(pattern, code):
            start = match.start()
            while code[start].isspace():
                start += 1
            if SCOPES.ordinary_depth_at(code, start) == (0, 0, 0):
                end = PROOF._rust_item_end(code, start)
                require(end is not None, "complete actual module constant/type")
                found.append((start, end + 1))
        require(len(found) == 1, "unique actual module constant/type")
        return found[0]
    raise PROOF.VerificationFailure("unknown fixed provider scope")


def module_shape(code, original):
    """Keep root declarations/imports/attributes closed, including extra impls.

    Actual function/impl bodies are separately fixed by their selected scopes.
    Prefixes and the final tail retain any other module code, so inserting a
    second impl, raw getter, alias, or macro cannot hide between those scopes.
    """
    result = []
    cursor = 0
    pattern = r"\b(?:use|mod|type|const|static|struct|enum|trait|impl|fn|extern|macro_rules)\b"
    for match in re.finditer(pattern, code):
        if match.start() < cursor or SCOPES.ordinary_depth_at(code, match.start()) != (0, 0, 0):
            continue
        end = PROOF._rust_item_end(code, match.start())
        require(end is not None, "complete actual root declaration")
        prefix = code[cursor:match.start()]
        attributes = []
        for attribute in re.finditer(r"#\[", prefix):
            begin = cursor + attribute.start()
            stop = PROOF._matching_delimiter(code, begin + 1, "[", "]")
            require(stop is not None and stop < match.start(), "complete actual root attribute")
            attributes.append(original[begin:stop + 1])
        if code[end] != "}" or match.group() in ("use", "mod", "type", "const", "static", "extern", "macro_rules"):
            identity = " ".join(code[match.start():end + 1].split())
        else:
            opening = SCOPES.ordinary_body_open(code, match.start(), end)
            identity = " ".join(code[match.start():opening].split())
        result.append({"prefix": " ".join(prefix.split()), "attributes": attributes, "identity": identity})
        cursor = end + 1
    result.append({"tail": " ".join(code[cursor:].split())})
    return result


def require_scopes(path, source):
    code, original = active_source(source)
    require(module_shape(code, original) == CONTRACT["module_shapes"][path],
            "actual provider module declarations/imports changed: " + path)
    for guard in CONTRACT["scopes"][path]:
        start, end = actual_scope(code, guard["selector"])
        require(hashlib.sha256(code[start:end].encode()).hexdigest() == guard["masked_sha256"],
                "actual provider code scope changed: " + path)
        require(hashlib.sha256(original[start:end].encode()).hexdigest() == guard["literal_source_sha256"],
                "actual provider literal/visibility scope changed: " + path)
    for spec in CONTRACT["mounts"].get(path, ()):
        SCOPES.ordinary_mount_span(PROOF, code, source, spec)


class ResidentProviderLocalReadClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def original_verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def verifies(self, path, source):
        self.original_verifies(path, source)
        require_scopes(path, source)

    def attack(self, case):
        path = case["path"]
        source = (ROOT / path).read_text()
        code, _ = active_source(source)
        span = SCOPES.ordinary_select_scope(
            PROOF, code, {"kind": "unique_function", "name": case["function"]}
        )
        marker = case["marker"]
        pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", marker))
        if marker[0].isalnum() or marker[0] == "_":
            pattern = r"(?<!\w)" + pattern
        if marker[-1].isalnum() or marker[-1] == "_":
            pattern += r"(?!\w)"
        found = list(re.finditer(pattern, code[span["start"]:span["end"]]))
        self.assertTrue(found, (path, case["function"], marker))
        self.verifies(path, source)
        for occurrence, match in enumerate(found):
            start = span["start"] + match.start()
            end = span["start"] + match.end()
            changed = source[:start] + case.get("replacement", "") + source[end:]
            self.assertNotEqual(source, changed)
            with self.subTest(path=path, function=case["function"], marker=marker, occurrence=occurrence):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, changed)

    def attack_group(self, group):
        self.assertTrue(CONTRACT["attacks"][group])
        for case in CONTRACT["attacks"][group]:
            self.attack(case)

    def test_exact_boundary_inventory_and_original_authority_are_preserved(self):
        rows = PROOF._boundary_rows(self.manifest)
        PROOF._verify_privileged_inventory(self.manifest, rows)
        self.assertEqual(len(rows), CONTRACT["boundary_count"])
        self.assertEqual(self.manifest["source_roots"], ["codex-rs"])
        self.assertEqual(self.manifest["ignored_path_fragments"], ["/tests/", "/examples/", "_tests.rs"])
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))
        checked = {key: self.manifest[key] for key in (
            "boundary", "privileged_inventory", "authority", "source_roots", "ignored_path_fragments")}
        self.assertEqual(hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                         CONTRACT["complete_boundary_sha256"])
        self.assertEqual(self.manifest["boundary"][569:], CONTRACT["new_boundaries"])

    def test_every_scope_mount_and_public_export_is_checked(self):
        # No dormant optional guard map: every prepared production path runs.
        for path in CONTRACT["scopes"]:
            with self.subTest(actual_provider_scope=path):
                self.verifies(path, (ROOT / path).read_text())
        source = (ROOT / (AGENT + "lib.rs")).read_text()
        code, _ = active_source(source)
        for export in CONTRACT["exports"]:
            self.assertEqual(source.count(export), 1)
            match = re.search(re.escape(export), code)
            self.assertIsNotNone(match)
            self.assertEqual(SCOPES.ordinary_depth_at(code, match.start()), (0, 0, 0))

    def test_full_source_collector_rejects_extra_and_removed_new_callers(self):
        roots = PROOF._string_tuple(self.manifest, "source_roots")
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        self.assertEqual(roots, ("codex-rs",))
        self.assertEqual(ignored, ("/tests/", "/examples/", "_tests.rs"))
        sources = {path.relative_to(ROOT).as_posix(): PROOF._strip_cfg_test_items(
            PROOF._strip_rust_non_code(path.read_text(encoding="utf-8")))
            for path in PROOF._source_files(ROOT, roots)}
        injection = AGENT + "unregistered_provider_readback_consumer.rs"
        self.assertNotIn(injection, sources)
        self.assertFalse(PROOF._is_ignored(injection, ignored))
        for expected in CONTRACT["new_boundaries"]:
            row = self.boundaries[expected["id"]]
            self.assertEqual(row.product_callers, tuple(expected["product_callers"]))
            PROOF._verify_boundary(ROOT, row, sources, ignored)
            method = row.symbol.rsplit("::", 1)[-1]
            if row.receiver_type:
                attempts = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}",
                    f"fn bypass(owner: &{row.receiver_type}) {{ {row.receiver_type}::{method}(owner); }}",
                )
            else:
                attempts = (f"fn bypass() {{ {row.symbol}(); }}",)
            for attempt in attempts:
                changed = dict(sources)
                changed[injection] = attempt
                with self.subTest(boundary=row.identifier, extra=attempt):
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, changed, ignored)
            for admitted in row.product_callers:
                changed_row = replace(row, product_callers=tuple(p for p in row.product_callers if p != admitted))
                with self.subTest(boundary=row.identifier, removed=admitted):
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, changed_row, sources, ignored)

    def test_sealed_clones_keep_the_same_owner_slot_and_permit(self):
        self.attack_group("sealed_clones")

    def test_original_t_e_and_v_s_c_identity_checks_cannot_be_removed(self):
        self.attack_group("original_identity")

    def test_local_capacity_cancellation_and_final_deadlines_cannot_be_removed(self):
        self.attack_group("local_budget")

    def test_readiness_reuses_the_same_next_use_lane(self):
        self.attack_group("readiness")

    def test_version_rechecks_current_around_each_actual_response(self):
        self.attack_group("version_current")

    def test_root_handoff_keeps_real_peers_rights_and_absolute_deadlines(self):
        self.attack_group("root_handoff")

    def test_root_registration_selects_fresh_or_readonly_without_wire_authority(self):
        self.attack_group("root_service")

    def test_shared_sealing_requires_completed_original_authenticated_clients(self):
        self.attack_group("shared_seals")

    def test_actual_protocol_literals_reject_same_length_changes_and_comment_bait(self):
        for path, selector in CONTRACT["protocol_items"]:
            source = (ROOT / path).read_text()
            code, _ = active_source(source)
            start, end = actual_scope(code, selector)
            body = source[start:end]
            found = re.search(r'(b?")([^"\\]+)(")', body)
            self.assertIsNotNone(found, (path, selector))
            first = start + found.start(2)
            changed = source[:first] + ("x" if source[first] != "x" else "y") + source[first + 1:]
            changed += "\n/* unchanged old literal is not live code: " + body.replace("*/", "* /") + " */\n"
            self.verifies(path, source)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(path, changed)

    def test_comments_and_nested_dead_scopes_cannot_supply_live_checks(self):
        for path, function in CONTRACT["decoy_functions"]:
            source = (ROOT / path).read_text()
            code, _ = active_source(source)
            span = SCOPES.ordinary_select_scope(PROOF, code, {"kind": "unique_function", "name": function})
            start, end = span["start"], span["end"]
            opening = code.index("{", start, end)
            original_body = source[opening + 1:end - 1]
            variants = (
                "/* " + original_body.replace("*/", "* /") + " */ panic!();",
                "fn unused_original_checks() {" + original_body + "} panic!();",
            )
            self.verifies(path, source)
            for replacement in variants:
                changed = source[:opening + 1] + replacement + source[end - 1:]
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, changed)

    def test_an_additional_impl_or_raw_getter_cannot_bypass_fixed_scopes(self):
        for filename, owner in (
            ("circuit_learning_local_read.rs", "OriginalCircuitPublishedLocalReadV1"),
            ("circuit_selection_local_predecessor.rs", "OriginalCircuitSelectionLocalReadbackV1"),
        ):
            path = AGENT + filename
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            changed = source + "\nimpl " + owner + " { pub fn unregistered_owner(&self) -> &std::sync::Arc<Original> { &self.original } }\n"
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(path, changed)

    def test_root_custody_consumes_original_values_and_requires_real_root(self):
        self.attack_group("root_custody_consumption")

    def test_root_cold_entry_rechecks_original_publication_without_reprepare(self):
        self.attack_group("root_cold_original_recovery")

    def test_root_task_factory_keeps_original_task_cell_and_drain_custody(self):
        self.attack_group("root_task_same_cell")



if __name__ == "__main__":
    unittest.main()
