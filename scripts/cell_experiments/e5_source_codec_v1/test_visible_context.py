"""Independent, synthetic semantic-boundary checks; no upstream code executes."""

import ast
import unittest

from source_actions import canonical
from source_units import names, sha
from visible_context import select


def material(runtime, task, cases):
    identity = {
        "source_id": "synthetic:only",
        "runtime_roots": ["pkg"],
        "test_paths": sorted(p for p in task if p.startswith("tests/test_")),
        "selector": "fixed_all_selected",
        "runtime": [
            {"path": p, "sha256": sha(b), "bytes": len(b)}
            for p, b in sorted(runtime.items())
        ],
        "task": [
            {"path": p, "sha256": sha(b), "bytes": len(b)}
            for p, b in sorted(task.items())
        ],
        "cases_sha256": sha(canonical(cases)),
    }
    return {
        "identity": identity,
        "identity_sha256": sha(canonical(identity)),
        "runtime": runtime,
        "task": task,
        "cases": cases,
    }


def case(
    name="test_value", classname="tests.test_core", failure="original assertion failed"
):
    return {"classname": classname, "name": name, "failure": failure, "skipped": False}


class VisibleContext(unittest.TestCase):
    def test_nested_arguments_stores_defaults_and_decorators_do_not_hide_globals(self):
        node = ast.parse(
            "@DEC(DEFAULT)\ndef outer(arg=DEFAULT):\n global GLOBAL\n def inner(GLOBAL):\n  VALUE=0\n  return GLOBAL\n return VALUE + GLOBAL\n"
        ).body[0]
        self.assertEqual(names(node), ["DEC", "DEFAULT", "GLOBAL", "VALUE"])
        runtime = {
            "pkg/core.py": b"VALUE=7\ndef outer():\n def inner(VALUE):\n  return VALUE\n return VALUE\n"
        }
        task = {
            "tests/test_core.py": b"from pkg.core import outer\ndef test_value():\n assert outer()==7\n"
        }
        out = select(material(runtime, task, [case()]))
        self.assertTrue(out["v1_static_context_closed"], out["blockers"])
        self.assertIn("VALUE=7\n", out["prompt"])

    def test_shadowed_builtin_is_a_real_dependency(self):
        runtime = {
            "pkg/core.py": b'def str(value):\n return "custom"\ndef outer():\n return str(1)\n'
        }
        task = {
            "tests/test_core.py": b'from pkg.core import outer\ndef test_value():\n assert outer()=="custom"\n'
        }
        out = select(material(runtime, task, [case()]))
        self.assertIn('def str(value):\n return "custom"\n', out["prompt"])

    def test_complete_grouped_import_does_not_select_unused_function_bodies(self):
        runtime = {
            "pkg/core.py": b'def wanted():\n return 1\ndef unused():\n return "'
            + b"x" * 100000
            + b'"\n'
        }
        task = {
            "tests/test_core.py": b"from pkg.core import wanted, unused\ndef test_value():\n assert wanted()==1\n"
        }
        out = select(material(runtime, task, [case()]))
        self.assertIn("from pkg.core import wanted, unused", out["prompt"])
        self.assertIn("def wanted():\n return 1", out["prompt"])
        self.assertNotIn("def unused():", out["prompt"])
        self.assertTrue(out["v1_static_context_closed"], out["blockers"])

    def test_class_initial_state_and_inherited_method_are_complete(self):
        runtime = {
            "pkg/core.py": b"VALUE=7\nclass Base:\n def __init__(self):\n  self.value=VALUE\n def read(self):\n  return self.value\nclass Box(Base):\n pass\n"
        }
        task = {
            "tests/test_core.py": b"from pkg.core import Box\ndef test_value():\n assert Box().read()==7\n"
        }
        out = select(material(runtime, task, [case()]))
        self.assertTrue(out["v1_static_context_closed"], out["blockers"])
        for text in (
            "class Base:\n",
            "class Box(Base):\n",
            "self.value=VALUE",
            "def read(self):",
            "VALUE=7",
        ):
            self.assertIn(text, out["prompt"])

    def test_every_parameter_and_required_fixture_retained_without_unrelated_file(self):
        runtime = {
            "pkg/core.py": b"def outer(value):\n return value\n",
            "pkg/unused.py": b'VALUE="' + b"x" * 100000 + b'"\n',
        }
        task = {
            "tests/test_core.py": b'import pytest\nfrom pkg.core import outer\n@pytest.mark.parametrize("value", [1,2,3])\ndef test_value(value, made):\n assert outer(value)==value\n',
            "tests/conftest.py": b"import pytest\n@pytest.fixture\ndef made():\n return 9\n@pytest.fixture(autouse=True)\ndef configure():\n yield\n",
        }
        cases = [
            case("test_value[1]"),
            case("test_value[2]", failure=None),
            case("test_value[3]", failure=None),
        ]
        out = select(material(runtime, task, cases))
        self.assertEqual(out["selected_case_count"], 3)
        self.assertIn('@pytest.mark.parametrize("value", [1,2,3])', out["prompt"])
        self.assertIn("def made():\n return 9", out["prompt"])
        self.assertIn("def configure():\n yield", out["prompt"])
        self.assertNotIn("pkg/unused.py", out["prompt"])
        self.assertTrue(out["v1_static_context_closed"], out["blockers"])

    def test_indirect_parameters_require_their_full_fixture(self):
        runtime = {"pkg/core.py": b"def outer(value):\n return value\n"}
        task = {
            "tests/test_core.py": b'import pytest\nfrom pkg.core import outer\n@pytest.mark.parametrize("value", [1,2], indirect=True)\ndef test_value(value):\n assert outer(value)==value\n'
        }
        out = select(
            material(runtime, task, [case("test_value[1]"), case("test_value[2]")])
        )
        self.assertIn(
            "required fixture binding absent: tests/test_core.py:value", out["blockers"]
        )

    def test_generated_case_and_dynamic_namespace_are_explicit_blockers(self):
        runtime = {"pkg/core.py": b"def outer(value):\n return globals()[value]\n"}
        task = {
            "tests/test_core.py": b'from pkg.core import outer\ndef test_value():\n assert outer("x")==1\n'
        }
        out = select(material(runtime, task, [case(), case("test_generated_123")]))
        self.assertEqual(len(out["unresolved_cases"]), 1)
        self.assertTrue(
            any("dynamic namespace dependency" in x for x in out["blockers"])
        )
        self.assertFalse(out["v1_static_context_closed"])

    def test_interface_rejects_after_channels_and_before_tampering(self):
        value = material(
            {"pkg/core.py": b"def outer():\n return 1\n"},
            {
                "tests/test_core.py": b"from pkg.core import outer\ndef test_value():\n assert outer()==2\n"
            },
            [case()],
        )
        first = select(value)
        self.assertEqual(first, select(value))
        with self.assertRaisesRegex(ValueError, "sanitized"):
            select({**value, "after": {}})
        value["runtime"]["pkg/core.py"] += b"# changed\n"
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            select(value)

    def test_missing_global_and_module_initialization_do_not_silently_close(self):
        runtime = {"pkg/core.py": b"configure()\ndef outer():\n return MISSING\n"}
        task = {
            "tests/test_core.py": b"from pkg.core import outer\ndef test_value():\n assert outer()==1\n"
        }
        out = select(material(runtime, task, [case()]))
        self.assertFalse(out["v1_static_context_closed"])
        self.assertTrue(
            any(
                "unresolved global dependency" in b and "MISSING" in b
                for b in out["blockers"]
            )
        )
        self.assertTrue(
            any("module initialization effect unmodeled" in b for b in out["blockers"])
        )

    def test_inherited_test_keeps_real_execution_class_and_setup(self):
        runtime = {"pkg/core.py": b"def outer():\n return 1\n"}
        task = {
            "tests/test_core.py": b"from pkg.core import outer\nclass Base:\n def test_value(self):\n  assert outer()==1\nclass Derived(Base):\n def setup_method(self):\n  self.ready=True\n"
        }
        out = select(
            material(runtime, task, [case(classname="tests.test_core.Derived")])
        )
        self.assertEqual(out["unresolved_cases"], [])
        self.assertIn("class Derived(Base):", out["prompt"])
        self.assertIn("def setup_method(self):", out["prompt"])
        self.assertIn("def test_value(self):", out["prompt"])

    def test_literal_parameter_paths_retain_every_complete_fixture(self):
        runtime = {"pkg/core.py": b"def outer(value):\n return value\n"}
        task = {
            "tests/test_core.py": b'import os\nimport pytest\nfrom pkg.core import outer\ndef compare(folder, filename):\n path=os.path.join("tests",folder,filename+".txt")\n with open(path) as file:\n  assert outer(file.read())\n@pytest.mark.parametrize("filename", ["first","second"])\ndef test_value(filename):\n compare("fixtures",filename)\n',
            "tests/fixtures/first.txt": b"whole first fixture\n",
            "tests/fixtures/second.txt": b"whole second fixture\n",
        }
        out = select(
            material(
                runtime, task, [case("test_value[first]"), case("test_value[second]")]
            )
        )
        self.assertEqual(
            out["task_fixture_resolution"]["paths"],
            ["tests/fixtures/first.txt", "tests/fixtures/second.txt"],
        )
        self.assertTrue(out["v1_static_context_closed"], out["blockers"])
        self.assertIn("whole first fixture\n", out["prompt"])
        self.assertIn("whole second fixture\n", out["prompt"])

    def test_branch_rebinding_and_read_before_assignment_cannot_certify_fixture(self):
        runtime = {"pkg/core.py": b"def outer():\n return 1\n"}
        for body in (
            ' if outer():\n  name="other"\n with open(name) as f:\n  assert f.read()\n',
            ' with open(path) as f:\n  assert f.read()\n path="tests/fixture.txt"\n',
        ):
            task = {
                "tests/test_core.py": (
                    'import pytest\nfrom pkg.core import outer\n@pytest.mark.parametrize("name",["tests/fixture.txt"])\ndef test_value(name):\n'
                    + body
                ).encode(),
                "tests/fixture.txt": b"original fixture\n",
            }
            out = select(
                material(runtime, task, [case("test_value[tests/fixture.txt]")])
            )
            self.assertTrue(
                any("no complete static fixture binding" in b for b in out["blockers"])
            )
            self.assertFalse(out["v1_static_context_closed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
