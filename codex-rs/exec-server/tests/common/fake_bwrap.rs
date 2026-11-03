use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(crate) fn write_fake_bwrap(bin_dir: &Path) -> anyhow::Result<PathBuf> {
    std::fs::create_dir_all(bin_dir)?;
    let fake_bwrap = bin_dir.join("bwrap");
    // Resolve the declared binary before callers prepend this fixture directory to PATH.
    let real_bwrap = codex_utils_cargo_bin::cargo_bin("bwrap")?;
    std::os::unix::fs::symlink(real_bwrap, bin_dir.join("bwrap.real"))?;
    std::fs::write(
        &fake_bwrap,
        r#"#!/bin/bash
set -euo pipefail

for arg in "$@"; do
  if [[ "${arg}" == "--help" ]]; then
    exec "${0}.real" "$@"
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
    exec "${0}.real" "$@"
    ;;
esac

printf '%s\n' "$*" >> "${0}.log"
if [[ -f "${0}.fail-once" ]]; then
  rm -f "${0}.fail-once"
  echo "forced fake bwrap failure" >&2
  exit 125
fi

exec "${0}.real" "$@"
"#,
    )?;
    let mut permissions = std::fs::metadata(&fake_bwrap)?.permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&fake_bwrap, permissions)?;
    Ok(fake_bwrap)
}
