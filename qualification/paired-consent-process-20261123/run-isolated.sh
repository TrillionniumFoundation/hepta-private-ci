#!/bin/sh
set -eu

case "$#" in 2) ;; *) echo "usage: run-isolated.sh HELPER CLI" >&2; exit 2 ;; esac

if [ "${HEPTA_CONSENT_INSIDE_NS-}" != 1 ]; then
  uid=$(id -u)
  gid=$(id -g)
  [ "$uid" -ne 0 ] && [ "$gid" -ne 0 ] || {
    echo "namespace bootstrap must start from a non-root account" >&2
    exit 1
  }
  script=$(realpath "$0")
  runner=$(realpath "$1")
  client=$(realpath "$2")
  box=$(mktemp -d)
  trap 'rmdir "$box"' EXIT
  user_ns=$(readlink /proc/self/ns/user)
  mount_ns=$(readlink /proc/self/ns/mnt)
  net_ns=$(readlink /proc/self/ns/net)
  pid_ns=$(readlink /proc/self/ns/pid)
  "${HEPTA_CONSENT_UNSHARE-unshare}" --user --map-root-user --mount --net \
    --pid --fork --kill-child --mount-proc -- \
    env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C HEPTA_CONSENT_INSIDE_NS=1 \
    HEPTA_CONSENT_HOST_UID="$uid" HEPTA_CONSENT_HOST_GID="$gid" \
    HEPTA_CONSENT_HOST_USER_NS="$user_ns" HEPTA_CONSENT_HOST_MOUNT_NS="$mount_ns" \
    HEPTA_CONSENT_HOST_NET_NS="$net_ns" HEPTA_CONSENT_HOST_PID_NS="$pid_ns" \
    HEPTA_CONSENT_BOX="$box" /bin/sh "$script" "$runner" "$client"
  exit
fi

# Fail before mounting or running any fixture if the bootstrap did not provide
# distinct user/mount/network/PID namespaces and exactly the original UID/GID.
[ "$$" -eq 1 ]
[ "$(id -u)" -eq 0 ] && [ "$(id -g)" -eq 0 ]
[ "$HEPTA_CONSENT_HOST_UID" -ne 0 ] && [ "$HEPTA_CONSENT_HOST_GID" -ne 0 ]
[ "$(readlink /proc/self/ns/user)" != "$HEPTA_CONSENT_HOST_USER_NS" ]
[ "$(readlink /proc/self/ns/mnt)" != "$HEPTA_CONSENT_HOST_MOUNT_NS" ]
[ "$(readlink /proc/self/ns/net)" != "$HEPTA_CONSENT_HOST_NET_NS" ]
[ "$(readlink /proc/self/ns/pid)" != "$HEPTA_CONSENT_HOST_PID_NS" ]
awk -v outside="$HEPTA_CONSENT_HOST_UID" 'NF != 3 || $1 != 0 || $2 != outside || $3 != 1 {exit 1} END {if (NR != 1) exit 1}' /proc/self/uid_map
awk -v outside="$HEPTA_CONSENT_HOST_GID" 'NF != 3 || $1 != 0 || $2 != outside || $3 != 1 {exit 1} END {if (NR != 1) exit 1}' /proc/self/gid_map

runner=$(realpath "$1")
client=$(realpath "$2")
box=$HEPTA_CONSENT_BOX
mount --make-rprivate /
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

# Replacing PID 1 is essential: no same-UID parent with a host filesystem root
# remains reachable through /proc. Namespace teardown cleans all mounts; the
# outer non-root shell removes only its empty directory after this exits.
exec chroot "$box" /usr/bin/setpriv --no-new-privs --bounding-set=-all \
  /usr/bin/sh -eu -c '
    [ "$$" -eq 1 ]
    [ "$(readlink /proc/1/root)" = / ]
    [ ! -e "$HEPTA_CONSENT_BOX" ]
    n=0 e=0 b=0
    while read -r key value rest; do
      case "$key:$value" in
        NoNewPrivs::1) n=1 ;;
        CapEff::0000000000000000) e=1 ;;
        CapBnd::0000000000000000) b=1 ;;
      esac
    done </proc/1/status
    [ "$n:$e:$b" = 1:1:1 ]
    while read -r interface rest; do
      case "$interface" in *:) [ "$interface" = lo: ] ;; esac
    done </proc/net/dev
    echo "isolated: non-root host mapping; private user/mount/network/PID; chrooted PID 1; no-new-privileges; zero effective/bounding capabilities"
    exec /runner /cli /development
  '
