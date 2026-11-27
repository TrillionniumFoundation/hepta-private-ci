"""Run the V8 Bazel canary detector regression suite in required repo-checks.

The existing repo-checks Bazel wrapper step discovers test_run_bazel*.py.
This adapter includes the entire existing detector TestCase without weakening
or replacing any tests or modifying the protected workflow.
"""

from test_v8_canary_changes import V8CanaryChangesTest  # noqa: F401
