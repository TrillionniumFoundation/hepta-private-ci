from pathlib import Path
import re, sys
root = Path(sys.argv[1])
# The one ignored History entry is the existing subprocess fixture;
# its parent control selects real SIGKILL cuts. It is not a skipped gate.
expected = {"factorial-kernel-tests": (6, 0), "factorial-example-tests": (6, 0),
    "header-binding-tests": (1, 0), "history-w1-tests": (5, 0),
    "history-import-tests": (28, 1), "cpu-completion-tests": (11, 0)}
for name, counts in expected.items():
    text = (root / (name + ".log")).read_text()
    rows = re.findall(r'^test result: ok\. ([0-9]+) passed; 0 failed; ([0-9]+) ignored;', text, re.M)
    if rows != [tuple(map(str, counts))]:
        raise SystemExit(name + ': exact native controls did not execute')
history = (root / 'history-import-tests.log').read_text()
for name in (
    'final_resource_completion_preserves_error_priority_and_original_deadline',
    'final_resource_expiry_keeps_committed_history_and_settled_cpu',
):
    selector = 'ingress::history_import::tests::deadline_controls::' + name
    rows = re.findall(r'^test ' + re.escape(selector) + r' \.\.\. ok$', history, re.M)
    if len(rows) != 1:
        raise SystemExit(selector + ': exact deadline control did not execute once')
codec_selector = ('ingress::history_import::tests::'
    'history_codec_snapshot_preserves_legacy_bytes_identity_and_deferred_profile_errors')
codec_rows = re.findall(r'^test ' + re.escape(codec_selector) + r' \.\.\. ok$', history, re.M)
if len(codec_rows) != 1:
    raise SystemExit(codec_selector + ': exact codec control did not execute once')