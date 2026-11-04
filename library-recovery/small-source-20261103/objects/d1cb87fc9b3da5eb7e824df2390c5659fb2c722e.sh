#!/usr/bin/env bash
# Hepta agent handoff: READ-ONLY survey. No git fetch, no mutation, no uploading of diagnostics.
# Usage: bash HEPTA_HOST_READONLY_AUDIT_2026-10-19.sh /path/to/hepta-private-ci [/other/worktree ...]
# Secrets are not collected: do not run `env`, `ps ... args`, `git remote -v`, or print credentials.
set -u
set -o pipefail
umask 077
export LC_ALL=C
printf '%s\n' '==== HEPTA HOST READ-ONLY AUDIT ===='
printf 'host='; hostname 2>/dev/null || true
printf 'time_utc='; date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true
printf 'uname='; uname -srm 2>/dev/null || true
printf '\n%s\n' '== Runtime/toolchain (no secrets) =='
for tool in git rustc cargo just bazel gh python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    case "$tool" in
      gh) printf 'gh: installed (not displaying credentials)\n' ;;
      *) printf '%s: ' "$tool"; "$tool" --version 2>&1 | head -n 1 || true ;;
    esac
  else
    printf '%s: not found\n' "$tool"
  fi
done
printf '\n%s\n' '== Disk and inodes =='
df -h 2>/dev/null || true
df -i 2>/dev/null || true
printf '\n%s\n' '== Relevant processes (PID/PPID/elapsed/status/comm ONLY, no arguments) =='
if ps -eo pid=,ppid=,etimes=,stat=,comm= >/dev/null 2>&1; then
  ps -eo pid=,ppid=,etimes=,stat=,comm= | grep -Ei '(^|[[:space:]])(cargo|rustc|bazel|just|codex|agent|hepta|runner|pytest|nextest|tmux|screen|python|node)(-|[[:space:]]|$)' | head -n 160 || true
fi
printf '\n%s\n' '== Terminal sessions/services/containers (names/status only) =='
if command -v tmux >/dev/null 2>&1; then tmux list-sessions 2>/dev/null || true; fi
if command -v screen >/dev/null 2>&1; then screen -ls 2>/dev/null || true; fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user --no-pager --plain --no-legend list-units --type=service --all 2>/dev/null | grep -Ei 'hepta|codex|agent|runner' | head -n 60 || true
fi
if command -v docker >/dev/null 2>&1; then
  docker ps --format 'name={{.Names}} status={{.Status}} image={{.Image}}' 2>/dev/null | head -n 60 || true
fi
if [ "$#" -eq 0 ]; then
  printf '\n%s\n' 'No worktree path argument passed. Re-run with one or more verified repo paths.'
else
  for candidate in "$@"; do
    printf '\n==== REPO ARGUMENT: %s ====\n' "$candidate"
    if ! [ -d "$candidate" ]; then printf '%s\n' 'not a directory'; continue; fi
    if ! git -C "$candidate" rev-parse --is-inside-work-tree 2>/dev/null | grep -qx true; then
      printf '%s\n' 'not a git worktree'; continue
    fi
    root=$(git -C "$candidate" rev-parse --show-toplevel 2>/dev/null || true)
    printf 'worktree_root=%s\n' "$root"
    remote=$(git -C "$root" remote get-url origin 2>/dev/null || true)
    # Never print the URL itself: HTTPS remote may contain embedded tokens.
    if printf '%s\n' "$remote" | grep -Eq '(^|[:/])TrillionniumFoundation/hepta-private-ci(\.git)?$'; then
      printf '%s\n' 'origin: expected hepta-private-ci slug found'
    else
      printf '%s\n' 'origin: NOT VERIFIED (inspect privately before using as this repo)'
    fi
    printf '%s\n' 'HEAD:'
    git -C "$root" rev-parse HEAD 2>/dev/null || true
    printf '%s\n' 'status (file names only, no contents):'
    git -C "$root" status --short --branch 2>/dev/null | head -n 140 || true
    printf '%s\n' 'worktrees:'
    git -C "$root" worktree list --porcelain 2>/dev/null | head -n 150 || true
    printf '%s\n' 'branches:'
    git -C "$root" branch -vv 2>/dev/null | head -n 130 || true
    printf '%s\n' 'latest commits:'
    git -C "$root" log -n 30 --format='%H %cI %s' 2>/dev/null || true
    printf '%s\n' 'locks/lease names (nonrecursive, no contents):'
    find "$root" -maxdepth 2 -type f \( -iname '*lease*' -o -iname '*lock*' \) -printf '%P\n' 2>/dev/null | head -n 80 || true
  done
fi
printf '\n%s\n' '== GitHub remote checks (READ-ONLY; if gh installed/authenticated) =='
if command -v gh >/dev/null 2>&1; then
  gh pr list --repo TrillionniumFoundation/hepta-private-ci --state open --limit 60 --json number,title,isDraft,headRefName,baseRefName,updatedAt,url 2>/dev/null || true
  gh run list --repo TrillionniumFoundation/hepta-private-ci --limit 30 2>/dev/null || true
else
  printf '%s\n' 'gh not installed: use GitHub integration from agent'
fi
printf '\n%s\n' '==== END READ-ONLY AUDIT ===='
