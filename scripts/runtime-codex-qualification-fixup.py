#!/usr/bin/env python3
"""Add real process-kill evidence to exact and synthetic qualification lanes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / ".github/workflows/runtime-codex-qualification.yml"
    text = path.read_text(encoding="utf-8")

    exact_marker = '''      - name: Native worker host
        run: >-
          python3 scripts/runtime-codex-qualification.py run
          --results "$RESULTS" --log-dir "$LOG_DIR" --name worker-host
          --cwd codex-rs -- cargo test --locked -p codex-hepta-infer-worker-host
'''
    exact_insert = '''      - name: Real Agentd process kill and restart
        run: >-
          python3 scripts/runtime-codex-qualification.py run
          --results "$RESULTS" --log-dir "$LOG_DIR" --name process-crash
          --cwd codex-rs -- cargo test --locked -p codex-hepta-agentd
          --test runtime_codex_process_crash
'''
    if exact_insert not in text:
        if exact_marker not in text:
            raise RuntimeError("exact native worker qualification marker missing")
        text = text.replace(exact_marker, exact_insert + exact_marker, 1)

    exact_require = '''          --require agentd-owner
          --require worker-host
'''
    exact_require_new = '''          --require agentd-owner
          --require process-crash
          --require worker-host
'''
    if exact_require_new not in text:
        if exact_require not in text:
            raise RuntimeError("exact process-crash gate marker missing")
        text = text.replace(exact_require, exact_require_new, 1)

    synthetic_marker = '''      - name: Crash matrix on merge candidate
        run: >-
          python3 scripts/runtime-codex-qualification.py run
          --results "$RESULTS" --log-dir "$LOG_DIR" --name crash-matrix
          --cwd codex-rs -- cargo test --locked -p codex-hepta-infer-worker-host
          --test runtime_codex_crash_matrix
'''
    synthetic_insert = '''      - name: Real process kill and restart on merge candidate
        run: >-
          python3 scripts/runtime-codex-qualification.py run
          --results "$RESULTS" --log-dir "$LOG_DIR" --name process-crash
          --cwd codex-rs -- cargo test --locked -p codex-hepta-agentd
          --test runtime_codex_process_crash
'''
    if synthetic_insert not in text:
        if synthetic_marker not in text:
            raise RuntimeError("synthetic crash matrix marker missing")
        text = text.replace(synthetic_marker, synthetic_insert + synthetic_marker, 1)

    synthetic_require = '''          --require owner-journal
          --require crash-matrix
'''
    synthetic_require_new = '''          --require owner-journal
          --require process-crash
          --require crash-matrix
'''
    if synthetic_require_new not in text:
        if synthetic_require not in text:
            raise RuntimeError("synthetic process-crash gate marker missing")
        text = text.replace(synthetic_require, synthetic_require_new, 1)

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
