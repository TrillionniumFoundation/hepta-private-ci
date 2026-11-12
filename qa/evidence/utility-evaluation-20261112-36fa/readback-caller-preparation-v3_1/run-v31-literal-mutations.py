"""Execute only the two new literal tests; complete membership remains separate."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent / "validation-source"
path = ROOT / "qa/b4-no-bypass/test_original_artifact_channel_source_closure.py"
spec = importlib.util.spec_from_file_location("artifact_v31_literal_mutations", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
names = (
    "test_actual_durable_directory_literals_reject_same_length_and_decoy_replacements",
    "test_actual_durable_filename_templates_reject_same_length_and_decoy_replacements",
)
suite = unittest.TestSuite(module.OriginalArtifactChannelClosureTests(name) for name in names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({
    "scope": "two new literal source-closure methods only",
    "test_methods_run": result.testsRun,
    "selected_methods": list(names),
    "failures": [case.id() for case, _ in result.failures],
    "errors": [case.id() for case, _ in result.errors],
    "skipped": [case.id() for case, _ in result.skipped],
    "was_successful": result.wasSuccessful(),
    "full_source_gate": "not_run",
    "full_caller_gate": "not_run",
    "runtime_tests": "not_run",
    "authority_granted": False,
}, sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
