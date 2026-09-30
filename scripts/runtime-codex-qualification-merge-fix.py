#!/usr/bin/env python3
"""Construct and verify the qualification merge in the canonical direction.

The source candidate is never used as the first parent. The deterministic
qualification commit has current base as parent 1, exact source head as parent
2, and the tree returned by `git merge-tree --write-tree` for that pair.

This construction helper is deleted after ordinary-source materialization.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/runtime-codex-qualification.yml"
HELPER = ROOT / "scripts/runtime-codex-qualification.py"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy block")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if marker in text:
        return
    raise RuntimeError(f"{marker}: legacy and migrated blocks are absent")


def main() -> None:
    replace_once(
        WORKFLOW,
        '''          git config user.name 'runtime.codex qualification'
          git config user.email 'runtime-codex-qualification@invalid'
          source_head="$(git rev-parse HEAD)"
          base_ref="${{ github.event.pull_request.base.ref }}"
          git fetch --no-tags origin "+refs/heads/$base_ref:refs/remotes/origin/$base_ref"
          current_base="$(git rev-parse "refs/remotes/origin/$base_ref")"
          git merge --no-ff --no-edit "$current_base"
          merge_head="$(git rev-parse HEAD)"
          merge_tree="$(git rev-parse 'HEAD^{tree}')"
''',
        '''          source_head="$(git rev-parse HEAD)"
          base_ref="${{ github.event.pull_request.base.ref }}"
          git fetch --no-tags origin "+refs/heads/$base_ref:refs/remotes/origin/$base_ref"
          current_base="$(git rev-parse "refs/remotes/origin/$base_ref")"
          test -z "$(git status --porcelain=v1)"

          merge_tree="$(git merge-tree --write-tree "$current_base" "$source_head")"
          test -n "$merge_tree"
          export GIT_AUTHOR_NAME='runtime.codex deterministic qualification merge'
          export GIT_AUTHOR_EMAIL='runtime-codex-qualification@invalid'
          export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
          export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
          export GIT_AUTHOR_DATE='2000-01-01T00:00:00Z'
          export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
          merge_head="$(printf '%s\\n' 'runtime.codex deterministic qualification merge' | \\
            git commit-tree "$merge_tree" -p "$current_base" -p "$source_head")"
          git checkout --detach "$merge_head"
          test "$(git rev-parse HEAD^1)" = "$current_base"
          test "$(git rev-parse HEAD^2)" = "$source_head"
          test "$(git rev-parse 'HEAD^{tree}')" = "$merge_tree"
          test -z "$(git status --porcelain=v1)"
''',
        "runtime.codex deterministic qualification merge",
    )

    replace_once(
        HELPER,
        '''        and parents[1] == source_head
        and parents[2] == base_head
''',
        '''        and parents[1] == base_head
        and parents[2] == source_head
''',
        "and parents[1] == base_head",
    )


if __name__ == "__main__":
    main()
