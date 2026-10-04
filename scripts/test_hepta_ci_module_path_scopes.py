"""Proposed conservative contract for literal module-path lexical scope.

This test-only preparation intentionally has red cases on c6f90. It must not be
presented as a passing implementation or as permission to drop opaque fallback.
Git fixtures are real; no compiler, build script or external program is run.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

try:
    from scripts import hepta_ci_dependencies as ci
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    import hepta_ci_dependencies as ci


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "codex-rs/hepta-a/src/lib.rs"
TARGET = "codex-rs/hepta-a/src/fixture.rs"
TOP_LEVEL = '#[cfg(test)]\n#[path = "fixture.rs"]\nmod fixture;\n'
INLINE = "#[cfg(test)]\nmod tests { fn unrelated() {} }\n"


class LiteralModuleScopeContract(unittest.TestCase):
    def parsed(self, text, tracked=None):
        return ci.module_source_inputs(
            SOURCE, text, {TARGET} if tracked is None else tracked
        )

    def test_real_hepta_paths_has_two_precise_top_level_edges(self):
        relative = "codex-rs/hepta-paths/src/lib.rs"
        tracked = {
            "codex-rs/hepta-paths/src/fleet.rs",
            "codex-rs/hepta-paths/src/native_root_tests.rs",
        }
        self.assertEqual(
            ci.module_source_inputs(
                relative, (ROOT / relative).read_text(encoding="utf-8"), tracked
            ),
            (tracked, False),
        )

    def test_unrelated_inline_sibling_does_not_make_top_level_path_opaque(self):
        for text in (INLINE + TOP_LEVEL, TOP_LEVEL + INLINE):
            with self.subTest(text=text):
                self.assertEqual(self.parsed(text), ({TARGET}, False))

    def test_balanced_lexical_noise_cannot_move_the_real_path_into_a_module(self):
        examples = [
            '// } #[path = "not-a-source.rs"] mod fake;\n',
            '/* } /* nested { */ #[path = "not-a-source.rs"] */\n',
            'const X: &str = "} mod fake { ";\n',
            'const X: &str = r###"} #[path = "not-a-source.rs"] mod fake;"###;\n',
            'const X: &[u8] = br##"} #[path = "not-a-source.rs"]"##;\n',
            "const X: char = '}'; const Y: u8 = b'{';\n",
            "fn same<'a>(x: &'a str) -> &'a str { x }\n",
            "fn 使用括号() { let _ = ([1, 2], { 3 }); }\n",
        ]
        for noise in examples:
            for position, text in (
                ("none", noise + TOP_LEVEL),
                ("before", INLINE + noise + TOP_LEVEL),
                ("after", noise + TOP_LEVEL + INLINE),
            ):
                with self.subTest(noise=noise, sibling=position):
                    self.assertEqual(self.parsed(text), ({TARGET}, False))

    def test_true_inline_path_remains_opaque(self):
        examples = [
            'mod tests { #[path = "fixture.rs"] mod fixture; }',
            '#[cfg(test)] mod tests { #[cfg(unix)] #[path = "fixture.rs"] mod fixture; }',
            'mod first { mod second { #[path = "fixture.rs"] mod fixture; } }',
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertTrue(self.parsed(text)[1])

    def test_cfg_attr_and_unsupported_module_attributes_remain_opaque(self):
        examples = [
            '#[cfg_attr(unix, path = "fixture.rs")] mod fixture;',
            '#[cfg_attr(test, cfg_attr(unix, path = "fixture.rs"))] mod fixture;',
            '#[unknown_module_rewriter]\n#[path = "fixture.rs"] mod fixture;',
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertTrue(self.parsed(text)[1])

    def test_known_inert_attributes_do_not_manufacture_unknown_paths(self):
        for text in (
            '#![recursion_limit = "256"]\nmod ordinary {}',
            "#[allow(warnings, clippy::all)]\nmod ordinary {}",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.parsed(text), (set(), False))
        self.assertEqual(
            self.parsed("#[allow(dead_code)]\n" + TOP_LEVEL), ({TARGET}, False)
        )

    def test_unicode_and_comment_separated_inline_modules_remain_opaque(self):
        for declaration in ("mod 测试", "mod/*comment*/tests"):
            with self.subTest(declaration=declaration):
                self.assertTrue(
                    self.parsed(
                        declaration + ' { #[path = "fixture.rs"] mod fixture; }'
                    )[1]
                )

    def test_unusual_lexemes_cannot_hide_a_nested_path(self):
        noise = [
            'const C: &core::ffi::CStr = c"}";',
            'const C: &core::ffi::CStr = cr#"}"#;',
            "const C: char = '\\u{7d}';",
            "fn labeled() { 'outer: loop { break 'outer; } }",
            *(
                "const X: &str = r" + "#" * count + '"}"' + "#" * count + ";"
                for count in (17, 255)
            ),
        ]
        for text in noise:
            with self.subTest(noise=text):
                self.assertTrue(
                    self.parsed(
                        "mod tests { " + text + ' #[path = "fixture.rs"] mod fixture; }'
                    )[1]
                )

    def test_comment_separated_attribute_tokens_do_not_hide_nested_path(self):
        for attribute in (
            '#[/* comment */path = "fixture.rs"]',
            '#[path/* comment */= "fixture.rs"]',
            '# /* comment */ [path = "fixture.rs"]',
        ):
            with self.subTest(attribute=attribute):
                self.assertTrue(
                    self.parsed("mod tests { " + attribute + " mod fixture; }")[1]
                )

    def test_path_inside_macro_tokens_never_becomes_a_precise_top_level_edge(self):
        for text in (
            'macro_rules! generated { () => { #[path = "fixture.rs"] mod fixture; } }',
            'unknown! { #[path = "fixture.rs"] mod fixture; }',
            'unknown! ( #[path = "fixture.rs"] mod fixture; );',
            'unknown! [ #[path = "fixture.rs"] mod fixture; ];',
        ):
            with self.subTest(text=text):
                self.assertTrue(self.parsed(text)[1])

    def test_unfinished_or_mismatched_tokens_fail_closed(self):
        for suffix in ("/* unfinished", 'const X: &str = "unfinished', "(", "[}", "{"):
            with self.subTest(suffix=suffix):
                self.assertTrue(self.parsed(TOP_LEVEL + suffix)[1])

    def test_missing_escaped_dynamic_and_control_paths_remain_opaque(self):
        for attribute in (
            '#[path = "missing.rs"]',
            '#[path = "../../../../escape.rs"]',
            '#[path = "/absolute.rs"]',
            '#[path = concat!("fixture", ".rs")]',
            '#[path = "line\\nfeed.rs"]',
        ):
            with self.subTest(attribute=attribute):
                self.assertTrue(self.parsed(attribute + "\nmod fixture;")[1])

    def test_unsupported_path_literal_escape_stays_opaque(self):
        self.assertTrue(self.parsed('#[path = "fi\\x78ture.rs"] mod fixture;')[1])

    def test_oversize_scan_falls_back_instead_of_authorizing_a_skip(self):
        self.assertTrue(self.parsed("// padding\n" * 110_000 + TOP_LEVEL)[1])

    def test_deep_scan_falls_back_instead_of_authorizing_a_skip(self):
        for depth, expected_opaque in ((128, False), (129, True)):
            with self.subTest(depth=depth):
                noise = "mod nested {" * depth + "}" * depth
                self.assertEqual(self.parsed(noise + TOP_LEVEL)[1], expected_opaque)


class ExactTreeScopeContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Module scope fixture")
        self.git("config", "user.email", "module-scope@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(
            "codex-rs/Cargo.toml",
            '[workspace]\nmembers=["hepta-a","hepta-b","hepta-unrelated"]\n',
        )
        for name in ("hepta-a", "hepta-b", "hepta-unrelated"):
            manifest = f'[package]\nname="{name}"\nversion="0.1.0"\n'
            if name == "hepta-b":
                manifest += '[dependencies]\nhepta-a={path="../hepta-a"}\n'
            self.write(f"codex-rs/{name}/Cargo.toml", manifest)
            self.write(f"codex-rs/{name}/src/lib.rs", "pub fn value() {}\n")
        self.write(SOURCE, INLINE + TOP_LEVEL)
        self.write(
            TARGET,
            'pub const INPUT: &str = include_str!("../../../docs/payload.md");\n',
        )
        self.write("docs/payload.md", "before\n")
        self.write("docs/navigation.md", "navigation before\n")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def write(self, path, text):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def change(self, path, text):
        self.write(path, text)
        return self.commit()

    def assert_scoped_plan(self, base, head, packages):
        result = ci.plan(self.root, base, head)
        self.assertEqual(
            (result["packages"], result["full_workspace"]), (packages, False)
        )

    def test_precise_sibling_does_not_select_unrelated_navigation(self):
        base = self.commit()
        head = self.change("docs/navigation.md", "navigation after\n")
        self.assert_scoped_plan(base, head, [])

    def test_real_embedded_input_still_selects_owner_and_reverse_consumer(self):
        base = self.commit()
        head = self.change("docs/payload.md", "after\n")
        self.assert_scoped_plan(base, head, ["hepta-a", "hepta-b"])

    def assert_nested_input_not_lost(self, declaration, directory):
        # A default .rs fixture would be scanned independently and hide the
        # missed traversal of the actual nested non-.rs module below.
        (self.root / TARGET).unlink()
        self.write(SOURCE, declaration + ' { #[path = "fixture.md"] mod fixture; }\n')
        self.write("codex-rs/hepta-a/src/fixture.md", "pub fn decoy() {}\n")
        self.write(
            f"codex-rs/hepta-a/src/{directory}/fixture.md",
            'pub const INPUT: &str = include_str!("../../../../docs/payload.md");\n',
        )
        base = self.commit()
        head = self.change("docs/payload.md", "after\n")
        self.assert_scoped_plan(base, head, ["hepta-a", "hepta-b"])

    def test_unicode_nested_non_rust_module_does_not_lose_its_input(self):
        self.assert_nested_input_not_lost("mod 测试", "测试")

    def test_comment_separated_nested_module_does_not_lose_its_input(self):
        self.assert_nested_input_not_lost("mod/*comment*/tests", "tests")

    def test_unknown_include_reason_survives_precise_sibling_path(self):
        self.write(
            SOURCE,
            TOP_LEVEL
            + '\nconst X: &str = include_str!(concat!(env!("OUT_DIR"), "/input"));\n',
        )
        base = self.commit()
        head = self.change("docs/navigation.md", "navigation after\n")
        self.assert_scoped_plan(base, head, ["hepta-a", "hepta-b"])

    def test_build_script_reason_survives_precise_sibling_path(self):
        self.write(SOURCE, TOP_LEVEL)
        self.write("codex-rs/hepta-a/build.rs", "fn main() {}\n")
        base = self.commit()
        head = self.change("docs/navigation.md", "navigation after\n")
        self.assert_scoped_plan(base, head, ["hepta-a", "hepta-b"])

    def test_old_opaque_graph_remains_authoritative_after_candidate_narrows(self):
        self.write(SOURCE, 'mod nested { #[path = "fixture.rs"] mod fixture; }\n')
        base = self.commit()
        head = self.change(SOURCE, INLINE + TOP_LEVEL)
        before, after = ci.graph(self.root, base), ci.graph(self.root, head)
        with self.subTest(revision="before"):
            self.assertIn("hepta-a", before.opaque_input_consumers)
        with self.subTest(revision="after"):
            self.assertNotIn("hepta-a", after.opaque_input_consumers)
        result = ci.select_packages(["docs/navigation.md"], before, after)
        self.assertEqual(
            (result["packages"], result["full_workspace"]),
            (["hepta-a", "hepta-b"], False),
        )


class PlannerEntrypointContract(unittest.TestCase):
    def command(self, arguments, cwd):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_original_blocking_ci_entrypoint_without_pythonpath(self):
        result = self.command(
            [
                "-m",
                "unittest",
                "-q",
                "scripts.tests.test_hepta_ci_scope",
                "scripts.tests.test_hepta_ci_dependencies",
            ],
            ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_script_entrypoint_outside_repository_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.command(
                [str(ROOT / "scripts/hepta_ci_dependencies.py"), "--help"], directory
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--tested", result.stdout)


if __name__ == "__main__":
    unittest.main()
