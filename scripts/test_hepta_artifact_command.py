"""Execute the repository test recipe with the qualifier's actual arguments.

The cargo executable is a diagnostic stand-in: these are Python/shell regressions,
not Rust compilation or native qualification evidence.
"""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import hepta_artifact_qualification as q


class CommandTests(unittest.TestCase):
    def command(self):
        module = ast.parse(Path(q.__file__).read_text())
        qualify = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'qualify')
        assignment = next(n for n in qualify.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'commands' for t in n.targets))
        expression = ast.Expression(assignment.value)
        return eval(compile(expression, '<qualifier commands>', 'eval'),
                    {'sys': sys, 'PACKAGE': q.PACKAGE, 'package': []})['tests']

    def run_recipe(self, arguments):
        repository = Path(q.__file__).resolve().parents[1]
        recipe = re.search(r'^test \*args:\n[ \t]+([^\n]*cargo nextest run[^\n]*)',
                           (repository / 'justfile').read_text(), re.MULTILINE).group(1)
        recipe = re.sub(r'\{\{ rust_min_stack \}\}', '8388608', recipe)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo = root / 'cargo'
            cargo.write_text('#!' + sys.executable + '\nimport json,sys\n'
                             'args=sys.argv[1:]\nprint(json.dumps(args))\n'
                             'sys.exit(0 if args.count("--no-fail-fast")==1 else 2)\n')
            cargo.chmod(0o700)
            environment = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ.get('PATH', '')}
            return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + recipe,
                                   'test-recipe', *arguments], env=environment,
                                  capture_output=True, text=True, timeout=10)

    def test_actual_qualifier_enters_nextest_with_one_fail_fast_flag(self):
        command = self.command()
        self.assertEqual(command[:2], ['just', 'test'])
        result = self.run_recipe(command[2:])
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(result.stdout)
        self.assertEqual(arguments[:2], ['nextest', 'run'])
        self.assertEqual(arguments.count('--no-fail-fast'), 1)
        self.assertEqual(arguments[arguments.index('--retries') + 1], '0')
        self.assertEqual(arguments[arguments.index('--run-ignored') + 1], 'all')
        self.assertIn('--locked', arguments)
        self.assertIn('--ignore-default-filter', arguments)
        self.assertEqual(arguments[arguments.index('-p') + 1], q.PACKAGE)

    def test_previous_duplicate_flag_fails_before_test_execution(self):
        result = self.run_recipe([*self.command()[2:], '--no-fail-fast'])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout).count('--no-fail-fast'), 2)


if __name__ == '__main__':
    unittest.main()
