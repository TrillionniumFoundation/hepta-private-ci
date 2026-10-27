import copy
import unittest

from windows_real_test_helpers import TARGETS, check_after

HEAD = "1" * 40
SOURCE = {
    "head": HEAD,
    "tree": "2" * 40,
    "trackedChanges": "",
    "cargoLockSha256": "3" * 64,
}
EXECUTABLES = {
    name: {"path": name + ".exe", "sha256": "4" * 64, "bytes": 100} for name in TARGETS
}
TOOLS = {
    name: {"path": name, "sha256": "5" * 64, "bytes": 100}
    for name in ("rustc", "cargo", "rustdoc")
}


def before():
    return {
        "status": "BUILT_REAL_TEST_HELPERS",
        "sourceBefore": dict(SOURCE),
        "executables": copy.deepcopy(EXECUTABLES),
        "toolFiles": copy.deepcopy(TOOLS),
    }


class RealTestHelperCustodyTests(unittest.TestCase):
    def test_exact_source_and_original_executables_are_required(self):
        self.assertTrue(check_after(HEAD, before(), SOURCE, "", EXECUTABLES, TOOLS))
        self.assertFalse(
            check_after("0" * 40, before(), SOURCE, "", EXECUTABLES, TOOLS)
        )
        self.assertFalse(
            check_after(HEAD, before(), SOURCE, "?? modified", EXECUTABLES, TOOLS)
        )

    def test_failed_build_and_changed_source_cannot_become_a_pass(self):
        bad = before()
        bad["status"] = "FAIL_REAL_TEST_HELPER_BUILD"
        self.assertFalse(check_after(HEAD, bad, SOURCE, "", EXECUTABLES, TOOLS))
        for key in SOURCE:
            changed = dict(SOURCE, **{key: "changed"})
            self.assertFalse(
                check_after(HEAD, before(), changed, "", EXECUTABLES, TOOLS)
            )

    def test_missing_or_unknown_targets_fail(self):
        for name in TARGETS:
            changed = copy.deepcopy(EXECUTABLES)
            del changed[name]
            self.assertFalse(check_after(HEAD, before(), SOURCE, "", changed, TOOLS))
        changed = dict(EXECUTABLES, unrelated={"path": "fake.exe"})
        self.assertFalse(check_after(HEAD, before(), SOURCE, "", changed, TOOLS))

    def test_changed_path_size_or_hash_is_not_the_built_target(self):
        for name in TARGETS:
            for key in ("path", "sha256", "bytes"):
                changed = copy.deepcopy(EXECUTABLES)
                changed[name][key] = "changed"
                self.assertFalse(
                    check_after(HEAD, before(), SOURCE, "", changed, TOOLS)
                )

    def test_missing_or_changed_compiler_tool_fails(self):
        for name in TOOLS:
            changed = copy.deepcopy(TOOLS)
            changed[name]["sha256"] = "changed"
            self.assertFalse(
                check_after(HEAD, before(), SOURCE, "", EXECUTABLES, changed)
            )
            del changed[name]
            self.assertFalse(
                check_after(HEAD, before(), SOURCE, "", EXECUTABLES, changed)
            )


if __name__ == "__main__":
    unittest.main()
