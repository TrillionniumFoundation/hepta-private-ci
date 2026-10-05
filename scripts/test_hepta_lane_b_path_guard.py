"""Canonical Lane B paths retain global delegated ownership and local boundaries."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("hepta-lane-b-path-guard.py")
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("lane_b_path_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)

AGENT_OWNER = "runtime.agentd"
AGENT_ROOT = "codex-rs/hepta-agentd"
LEDGER_OWNER = "learning.ledger"
LEDGER_ROOT = "codex-rs/hepta-learning-ledger"
MAP_PATH = "docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json"
TRUTH_PATH = "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
CODEX_BINDING = json.loads(
    (SCRIPT.parent.parent / "codex-rs/codex-app-server/BINDING.json").read_text(
        encoding="utf-8"
    )
)


class LaneBPathGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for directory in (
            AGENT_ROOT,
            LEDGER_ROOT,
            "qualification/lane-b",
            "docs/modules",
        ):
            (self.root / directory).mkdir(parents=True)
        for directory in (AGENT_ROOT, LEDGER_ROOT):
            self.source(f"{directory}/src/lib.rs")
        self.registry = {
            "modules": [
                {"id": AGENT_OWNER, "rootBindings": [{"path": AGENT_ROOT}]},
                {"id": LEDGER_OWNER, "rootBindings": [{"path": LEDGER_ROOT}]},
            ]
        }
        self.map = {
            "module": AGENT_OWNER,
            "resolvedRoots": [AGENT_ROOT],
            "operations": [
                {
                    "ownerEntrypoint": {
                        "role": "owner_entrypoint",
                        "path": f"{AGENT_ROOT}/src/lib.rs",
                        "symbol": "pub fn run(",
                        "buildTarget": "codex-hepta-agentd",
                    },
                    "delegatedCallees": [
                        {
                            "role": "delegated_callee",
                            "ownerModule": LEDGER_OWNER,
                            "path": f"{LEDGER_ROOT}/src/lib.rs",
                            "symbol": "pub fn run(",
                            "buildTarget": "codex-hepta-learning-ledger",
                        }
                    ],
                    "tests": [
                        {
                            "path": f"{AGENT_ROOT}/src/lib.rs",
                            "command": "fixture check",
                        }
                    ],
                }
            ],
        }
        self.truth = {"modules": [{"module": AGENT_OWNER, "mapPath": MAP_PATH}]}

    def source(self, path):
        selected = self.root / path
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text("pub fn run() {}\n", encoding="utf-8")

    def write(self, path, value):
        selected = self.root / path
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text(json.dumps(value), encoding="utf-8")

    def verify(self):
        self.write(TRUTH_PATH, self.truth)
        self.write("docs/modules/MODULES.json", self.registry)
        self.write(MAP_PATH, self.map)
        with contextlib.redirect_stdout(io.StringIO()):
            return GUARD.verify(self.root)

    def register_codex_alias(self):
        # Use the checked-in binding's actual schema, canonical owner identity
        # and implementation destination; only the repository tree is a fixture.
        binding = copy.deepcopy(CODEX_BINDING)
        alias = binding["declared_root"]
        implementation = binding["implementation_root"]
        self.source(f"{implementation}/src/lib.rs")
        self.registry["modules"][1] = {
            "id": binding["module"],
            "rootBindings": [{"path": alias}],
        }
        delegate = self.map["operations"][0]["delegatedCallees"][0]
        delegate.update(
            ownerModule=binding["module"],
            path=f"{implementation}/src/lib.rs",
            buildTarget="codex-app-server",
        )
        self.write(f"{alias}/BINDING.json", binding)
        return binding

    def direct_cargo_dependency(self, dependency_root, package_name):
        (self.root / "codex-rs/Cargo.toml").write_text(
            "[workspace]\n", encoding="utf-8"
        )
        (self.root / AGENT_ROOT / "Cargo.toml").write_text(
            '[package]\nname = "codex-hepta-agentd"\nversion = "0.0.0"\n'
            f'[dependencies]\n{package_name} = {{path = "../{Path(dependency_root).name}"}}\n',
            encoding="utf-8",
        )
        (self.root / dependency_root / "Cargo.toml").write_text(
            f'[package]\nname = "{package_name}"\nversion = "0.0.0"\n',
            encoding="utf-8",
        )

    def test_registered_cross_lane_delegate_is_not_a_lane_b_owner(self):
        before = copy.deepcopy(self.map)
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.map, before)
        self.assertEqual(self.map["resolvedRoots"], [AGENT_ROOT])
        self.assertEqual(
            self.map["operations"][0]["delegatedCallees"][0]["ownerModule"],
            LEDGER_OWNER,
        )

    def test_delegate_cannot_be_relabelled_to_the_caller_or_unknown_owner(self):
        for owner in (AGENT_OWNER, "unregistered.owner"):
            with self.subTest(owner=owner):
                self.map["operations"][0]["delegatedCallees"][0]["ownerModule"] = owner
                with self.assertRaises(GUARD.Invalid):
                    self.verify()

    def test_direct_cargo_dependency_cannot_launder_a_registered_source_owner(self):
        self.direct_cargo_dependency(LEDGER_ROOT, "codex-hepta-learning-ledger")
        delegate = self.map["operations"][0]["delegatedCallees"][0]
        delegate["ownerModule"] = AGENT_OWNER
        with self.assertRaisesRegex(
            GUARD.Invalid, "registered delegated owner mismatch"
        ):
            self.verify()

    def test_direct_cargo_dependency_preserves_the_registered_cross_lane_owner(self):
        self.direct_cargo_dependency(LEDGER_ROOT, "codex-hepta-learning-ledger")
        self.assertEqual(self.verify(), 0)
        self.assertEqual(
            self.map["operations"][0]["delegatedCallees"][0]["ownerModule"],
            LEDGER_OWNER,
        )

    def test_direct_cargo_dependency_can_navigate_an_unregistered_implementation(self):
        implementation = "codex-rs/core"
        self.source(f"{implementation}/src/lib.rs")
        self.direct_cargo_dependency(implementation, "codex-core")
        delegate = self.map["operations"][0]["delegatedCallees"][0]
        delegate.update(
            ownerModule=AGENT_OWNER,
            path=f"{implementation}/src/lib.rs",
            buildTarget="codex-core",
        )
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.map["resolvedRoots"], [AGENT_ROOT])

    def test_owned_entrypoint_cannot_escape_into_a_registered_delegate(self):
        self.map["operations"][0]["ownerEntrypoint"]["path"] = (
            f"{LEDGER_ROOT}/src/lib.rs"
        )
        with self.assertRaisesRegex(GUARD.Invalid, "owner-root escape"):
            self.verify()

    def test_map_cannot_enlarge_its_own_roots(self):
        self.map["resolvedRoots"].append(LEDGER_ROOT)
        with self.assertRaisesRegex(GUARD.Invalid, "registered owner roots mismatch"):
            self.verify()

    def test_map_cannot_replace_its_roots_with_an_unregistered_directory(self):
        self.source("unregistered/src/lib.rs")
        self.map["resolvedRoots"] = ["unregistered"]
        self.map["operations"][0]["ownerEntrypoint"]["path"] = "unregistered/src/lib.rs"
        with self.assertRaisesRegex(GUARD.Invalid, "registered owner roots mismatch"):
            self.verify()

    def test_duplicate_identity_and_ambiguous_roots_fail_closed(self):
        original = copy.deepcopy(self.registry)
        for module in (
            {"id": LEDGER_OWNER, "rootBindings": [{"path": LEDGER_ROOT}]},
            {"id": "inference.worker", "rootBindings": [{"path": LEDGER_ROOT}]},
        ):
            with self.subTest(module=module):
                self.registry = copy.deepcopy(original)
                self.registry["modules"].append(module)
                with self.assertRaisesRegex(GUARD.Invalid, "duplicate|ambiguous"):
                    self.verify()

    def test_nested_root_collision_is_rejected_even_without_a_delegate_to_it(self):
        nested = f"{LEDGER_ROOT}/submodule"
        self.source(f"{nested}/lib.rs")
        self.registry["modules"].append(
            {"id": "inference.worker", "rootBindings": [{"path": nested}]}
        )
        with self.assertRaisesRegex(GUARD.Invalid, "ambiguous registered source root"):
            self.verify()

    def test_duplicate_lane_module_identity_is_rejected(self):
        self.truth["modules"].append(copy.deepcopy(self.truth["modules"][0]))
        with self.assertRaisesRegex(GUARD.Invalid, "duplicate module index"):
            self.verify()

    def test_unregistered_lane_owner_is_rejected(self):
        self.truth["modules"][0]["module"] = "unregistered.owner"
        self.map["module"] = "unregistered.owner"
        with self.assertRaisesRegex(GUARD.Invalid, "unregistered module owner"):
            self.verify()

    def test_alias_root_keeps_the_registered_delegate_identity(self):
        binding = self.register_codex_alias()
        self.assertEqual(self.verify(), 0)
        binding["provider_authority"] = True
        self.write(f"{binding['declared_root']}/BINDING.json", binding)
        with self.assertRaisesRegex(GUARD.Invalid, "authority mismatch"):
            self.verify()

    def test_alias_cannot_change_the_registered_module_identity(self):
        binding = self.register_codex_alias()
        binding["module"] = LEDGER_OWNER
        self.write(f"{binding['declared_root']}/BINDING.json", binding)
        with self.assertRaisesRegex(GUARD.Invalid, "alias identity"):
            self.verify()

    def test_two_aliases_cannot_claim_the_same_implementation(self):
        binding = self.register_codex_alias()
        second = copy.deepcopy(binding)
        second.update(module="inference.worker", declared_root="codex-rs/second-alias")
        self.write(f"{second['declared_root']}/BINDING.json", second)
        self.registry["modules"].append(
            {
                "id": second["module"],
                "rootBindings": [{"path": second["declared_root"]}],
            }
        )
        with self.assertRaisesRegex(GUARD.Invalid, "ambiguous registered source root"):
            self.verify()

    def test_malformed_delegate_target_is_rejected_before_dependency_resolution(self):
        delegate = self.map["operations"][0]["delegatedCallees"][0]
        delegate["path"] = f"{AGENT_ROOT}/src/lib.rs"
        delegate["buildTarget"] = {"package": "codex-hepta-agentd"}
        with self.assertRaisesRegex(GUARD.Invalid, "build target"):
            self.verify()

    def test_repository_guard_accepts_actual_registered_cross_lane_delegates(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(GUARD.verify(), 0)


if __name__ == "__main__":
    unittest.main()
