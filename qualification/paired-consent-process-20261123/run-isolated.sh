#!/bin/sh
set -eu
case "$#" in 2) ;; *) echo "usage: run-isolated.sh HELPER CLI" >&2; exit 2 ;; esac
if [ "${HEPTA_CONSENT_INSIDE_NS-}" != 1 ]; then
  exec unshare --user --map-root-user --mount --net -- env HEPTA_CONSENT_INSIDE_NS=1 "$0" "$1" "$2"
fi
runner=$(realpath "$1")
client=$(realpath "$2")
mount --make-rprivate /
box=$(mktemp -d)
trap 'umount -R "$box" 2>/dev/null || :; rmdir "$box"' EXIT
mount -t tmpfs -o mode=700,size=32m tmpfs "$box"
for dir in usr lib lib64 proc; do
  if [ -d "/$dir" ]; then
    mkdir "$box/$dir"
    mount --bind "/$dir" "$box/$dir"
    mount -o remount,bind,ro "$box/$dir"
  fi
done
mkdir -m 0755 "$box/dev"
for name in null urandom; do
  touch "$box/dev/$name"
  mount --bind "/dev/$name" "$box/dev/$name"
done
mkdir -m 1777 "$box/tmp"
for pair in runner cli; do
  case "$pair" in runner) file=$runner ;; cli) file=$client ;; esac
  touch "$box/$pair"
  mount --bind "$file" "$box/$pair"
  mount -o remount,bind,ro "$box/$pair"
done
chroot "$box" /runner /cli /development
