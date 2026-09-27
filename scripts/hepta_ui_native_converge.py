#!/usr/bin/env python3
"""Materialize the reviewed ui.native convergence proposal exactly once.

This script transforms source and evidence declarations but grants no release,
production, signing, promotion, or independent-acceptance authority.
"""

from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]
NEW = "work/ui-native-integration-convergence-20260927"
MATERIALIZER = ROOT / ".github/materializers/hepta-ui-native-integration-converge.yml.txt"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def changed(path: str, transform) -> None:
    original = read(path)
    result = transform(original)
    if result == original:
        raise SystemExit(f"expected convergence change in {path}")
    write(path, result)


def extract_materializer() -> str:
    source = MATERIALIZER.read_text(encoding="utf-8")
    start_marker = "          python3 - <<'PY'\n"
    end_marker = "\n          PY\n"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    script = textwrap.dedent(source[start:end])

    lines = script.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if 'text = text.replace("ui-native-remediation-' in line
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one embedded concurrency replacement, found {len(matches)}"
        )
    index = matches[0]
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines[index] = indent + (
        'text = text.replace("ui-native-remediation-", '
        '"ui-native-convergence-", 1)'
    )
    script = "\n".join(lines) + "\n"

    # The historical current-source workflow never contained the old acceptance
    # branch token. It is converged explicitly below, rather than weakening the
    # audited materializer's replace_once helper.
    old = '''              ".github/workflows/hepta-ui-native-remediation.yml",
              ".github/workflows/hepta-ui-native-remediation-format.yml",
              ".github/workflows/hepta-ui-native-current-source.yml",
'''
    new = '''              ".github/workflows/hepta-ui-native-remediation.yml",
              ".github/workflows/hepta-ui-native-remediation-format.yml",
'''
    if script.count(old) != 1:
        raise SystemExit("embedded workflow convergence list changed")
    script = script.replace(old, new, 1)
    compile(script, "ui-native-convergence-materializer", "exec")
    return script


def converge_generator() -> None:
    def transform(text: str) -> str:
        result, count = re.subn(
            r"WRITE_BRANCHES = \{.*?\}\nINTEGRATION_ROOTS",
            "WRITE_BRANCHES = {BRANCH}\nINTEGRATION_ROOTS",
            text,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise SystemExit("generator write-branch set changed")
        return result

    changed("apps/hepta-native/tools/prepare_current_source.py", transform)


def converge_worker_error_path() -> None:
    old = '''        if let Err(error) = task.join_worker() {
            self.last_error = Some(error);
            return;
        }
        match outcome {
'''
    new = '''        let outcome = match task.join_worker() {
            Ok(()) => outcome,
            Err(error) => Err(error),
        };
        match outcome {
'''
    changed("apps/hepta-native/src/ui.rs", lambda text: text.replace(old, new, 1))


def converge_qualification_workflow() -> None:
    def transform(text: str) -> str:
        result, count = re.subn(
            r"branches: \[[^\n]+\]",
            f"branches: [{NEW}, main]",
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit("qualification branch trigger changed")
        return result.replace(
            "name: ui.native remediation required",
            "name: ui.native convergence required",
            1,
        )

    changed(".github/workflows/hepta-ui-native-remediation.yml", transform)


def converge_formatter_workflow() -> None:
    def transform(text: str) -> str:
        text = text.replace(
            "name: ui.native remediation branch formatter",
            "name: ui.native convergence formatter proposal",
            1,
        )
        result, count = re.subn(
            r"branches: \[[^\n]+\]",
            f"branches: [{NEW}]",
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit("formatter branch trigger changed")
        return result

    changed(".github/workflows/hepta-ui-native-remediation-format.yml", transform)


def converge_current_source_workflow() -> None:
    def transform(text: str) -> str:
        result, count = re.subn(
            r"on:\n  push:\n    branches: \[[^\n]+\]\n  workflow_dispatch:",
            "on:\n  workflow_dispatch:",
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit("current-source trigger changed")
        expression = "${" + "{ github.event_name == 'push' && github.sha || " + (
            "'work/ui-native-current-source-20260925' }}"
        )
        result = result.replace(expression, NEW, 1)
        old = '''          git fetch --no-tags origin             refs/heads/work/ui-native-current-source-20260925:refs/remotes/origin/work/ui-native-current-source-20260925             refs/heads/main:refs/remotes/origin/main
          candidate=$(git rev-parse HEAD)
          if test "$EVENT_NAME" = push; then
            test "$candidate" = "$EVENT_SHA"
          else
            test "$candidate" = "$(git rev-parse refs/remotes/origin/work/ui-native-current-source-20260925)"
          fi
          echo "candidate=$candidate" >> "$GITHUB_OUTPUT"
          echo "base=$(git rev-parse refs/remotes/origin/main)" >> "$GITHUB_OUTPUT"
'''
        new = '''          candidate=$(git rev-parse HEAD)
          base=a126987b84737dbc2ee2592442a314117bddb4a2
          git cat-file -e "$base^{commit}"
          echo "candidate=$candidate" >> "$GITHUB_OUTPUT"
          echo "base=$base" >> "$GITHUB_OUTPUT"
'''
        if old not in result:
            raise SystemExit("current-source identity block changed")
        return result.replace(old, new, 1)

    changed(".github/workflows/hepta-ui-native-current-source.yml", transform)


def converge_projection_workflow() -> None:
    def transform(text: str) -> str:
        text = text.replace(
            "      - work/ui-native-current-source-20260925",
            f"      - {NEW}",
            1,
        )
        old = '''          git fetch --no-tags origin \\
            refs/heads/main:refs/remotes/origin/main
          base=$(git rev-parse refs/remotes/origin/main)
'''
        new = '''          base=a126987b84737dbc2ee2592442a314117bddb4a2
          git cat-file -e "$base^{commit}"
'''
        if old not in text:
            raise SystemExit("projection merge-base block changed")
        return text.replace(old, new, 1)

    changed(".github/workflows/hepta-ui-native-projections.yml", transform)


def retire_acceptance_exporter() -> None:
    def transform(text: str) -> str:
        result, count = re.subn(
            r"on:\n  push:\n    branches: \[work/ui-native-acceptance-repair-20260927\]\n"
            r"    paths:\n      - scripts/hepta_ui_native_acceptance_finish.py\n"
            r"      - \.github/workflows/hepta-ui-native-acceptance-proposal.yml",
            "on:\n  workflow_dispatch:",
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit("acceptance exporter trigger changed")
        result = result.replace(
            "    if: github.repository == 'TrillionniumFoundation/hepta-private-ci' "
            "&& github.ref == 'refs/heads/work/ui-native-acceptance-repair-20260927'",
            "    if: false # superseded historical exporter retained for audit",
            1,
        )
        return result.replace(
            "HEPTA_UI_NATIVE_WRITE_BRANCH: work/ui-native-acceptance-repair-20260927",
            f"HEPTA_UI_NATIVE_WRITE_BRANCH: {NEW}",
            1,
        )

    changed(".github/workflows/hepta-ui-native-acceptance-proposal.yml", transform)


def main() -> None:
    if not MATERIALIZER.is_file():
        raise SystemExit("missing immutable ui.native convergence materializer")
    script = extract_materializer()
    exec(script, {"__name__": "__main__"})
    converge_generator()
    converge_worker_error_path()
    converge_qualification_workflow()
    converge_formatter_workflow()
    converge_current_source_workflow()
    converge_projection_workflow()
    retire_acceptance_exporter()


if __name__ == "__main__":
    main()
