#!/bin/sh
set -eu
case "$#" in 2) ;; *) echo "usage: run-on-ubuntu.sh HELPER CLI" >&2; exit 2 ;; esac
[ "$(id -u)" -ne 0 ]

# Ubuntu 24.04 restricts capabilities in an unprofiled user namespace. Install
# the documented per-executable userns permission for a root-owned copy of the
# system unshare binary. Do not disable AppArmor or change any global sysctl.
# The actual sandbox and test retain the invoking runner's non-root UID.
# https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions
policy_root=/run/hepta-consent-namespace
restriction=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
sudo mkdir -m 0755 "$policy_root"
profile_loaded=0
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$profile_loaded" -eq 1 ]; then
    sudo apparmor_parser -R "$policy_root/profile" || status=1
  fi
  sudo rm -f "$policy_root/profile" "$policy_root/unshare" || status=1
  sudo rmdir "$policy_root" || status=1
  [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = "$restriction" ] || status=1
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
sudo install -o root -g root -m 0755 /usr/bin/unshare "$policy_root/unshare"
sudo tee "$policy_root/profile" >/dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile hepta-consent-namespace /run/hepta-consent-namespace/unshare flags=(unconfined) {
  userns,
}
PROFILE
sudo apparmor_parser -a "$policy_root/profile"
profile_loaded=1
HEPTA_CONSENT_UNSHARE="$policy_root/unshare" \
  sh "$(dirname "$0")/run-isolated.sh" "$1" "$2"
