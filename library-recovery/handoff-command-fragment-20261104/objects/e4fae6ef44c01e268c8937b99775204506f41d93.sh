hostname; date -u; pwd
ps -eo pid,ppid,etime,stat,cmd --sort=-etime | head -n 120
pgrep -af 'hepta|codex|cargo|bazel|just|pytest|agent|runner' || true
tmux list-sessions 2>/dev/null || true
systemctl --user list-units --type=service --all 2>/dev/null | grep -Ei 'hepta|codex|agent|runner' || true
# 在每一个核实过的 Hepta 仓库目录执行：
git remote -v; git worktree list --porcelain; git status --porcelain=v1 -b
git branch -vv; git log -n 12 --format='%H %cI %s'
git rev-parse HEAD; git fetch --dry-run origin
# GitHub CLI 如已授权可用：
gh pr list --repo TrillionniumFoundation/hepta-private-ci --state open --limit 100
gh run list --repo TrillionniumFoundation/hepta-private-ci --limit 100
