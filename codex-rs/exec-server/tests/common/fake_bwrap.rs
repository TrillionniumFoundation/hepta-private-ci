use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context as _;

/// Records real namespace launches while retaining one explicit failure injection.
/// Resolve the real executable before installing the test's PATH wrapper.
pub(crate) fn write_fake_bwrap(bin_dir: &Path) -> anyhow::Result<PathBuf> {
    let real_bwrap_path = codex_sandboxing::find_system_bwrap_in_path()
        .context("real bubblewrap must be available on the original PATH")?;
    let real_bwrap = real_bwrap_path
        .to_str()
        .context("real bubblewrap path must be valid UTF-8 for the test wrapper")?;
    let real_bwrap = format!("'{}'", real_bwrap.replace('\'', "'\"'\"'"));

    std::fs::create_dir_all(bin_dir)?;
    let fake_bwrap = bin_dir.join("bwrap");
    std::fs::write(
        &fake_bwrap,
        r#"#!/bin/bash
set -euo pipefail
real_bwrap=__REAL_BWRAP__

for arg in "$@"; do
  if [[ "${arg}" == "--help" ]]; then
    exec "${real_bwrap}" "$@"
  fi
done

args=("$@")
command_start=-1
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == "--" ]]; then
    command_start=$((i + 1))
    break
  fi
done

if [[ "${command_start}" -lt 0 || "${command_start}" -ge "${#args[@]}" ]]; then
  echo "fake bwrap did not find an inner command" >&2
  exit 125
fi

cmd=("${args[@]:$command_start}")
case "${cmd[0]}" in
  /usr/bin/true|/bin/true|true)
    exec "${real_bwrap}" "$@"
    ;;
esac

printf '%s\n' "$*" >> "${0}.log"
if [[ -f "${0}.fail-once" ]]; then
  rm -f "${0}.fail-once"
  echo "forced fake bwrap failure" >&2
  exit 125
fi

exec "${real_bwrap}" "$@"
"#
        .replace("__REAL_BWRAP__", &real_bwrap),
    )?;
    let mut permissions = std::fs::metadata(&fake_bwrap)?.permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&fake_bwrap, permissions)?;
    Ok(fake_bwrap)
}
