use anyhow::Context;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(crate) fn write_fake_bwrap(bin_dir: &Path) -> anyhow::Result<PathBuf> {
    let real_bwrap = codex_utils_cargo_bin::cargo_bin("bwrap")?;
    let real_bwrap = real_bwrap
        .to_str()
        .context("bwrap test binary path is not valid UTF-8")?
        .replace('\'', "'\\''");
    std::fs::create_dir_all(bin_dir)?;
    let fake_bwrap = bin_dir.join("bwrap");
    let mut script = format!("#!/bin/bash\nreal_bwrap='{real_bwrap}'\n");
    script.push_str(
        r#"set -euo pipefail

for arg in "$@"; do
  if [[ "${arg}" == "--help" ]]; then
    exec "$real_bwrap" "$@"
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

# Capability probes must exercise the same binary without consuming fail-once.
if [[ "${command_start}" -lt 0 || "${command_start}" -ge "${#args[@]}" ]]; then
  exec "$real_bwrap" "$@"
fi

cmd=("${args[@]:$command_start}")
case "${cmd[0]}" in
  /usr/bin/true|/bin/true|true)
    exec "$real_bwrap" "$@"
    ;;
esac

printf '%s\n' "$*" >> "${0}.log"
if [[ -f "${0}.fail-once" ]]; then
  rm -f "${0}.fail-once"
  echo "forced fake bwrap failure" >&2
  exit 125
fi

# Preserve namespace options, argv0, and all inherited descriptors.
exec "$real_bwrap" "$@"
"#,
    );
    std::fs::write(&fake_bwrap, script)?;
    let mut permissions = std::fs::metadata(&fake_bwrap)?.permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&fake_bwrap, permissions)?;
    Ok(fake_bwrap)
}
