#!/bin/sh
set -eu

# Invoked through the test's private symlink. Keep the real host's PID so the
# parent can kill that process while its sessions have outstanding work.
proxy_dir=${0%/*}
IFS= read -r host_program < "$proxy_dir/host.program"
printf '%s\n' "$$" > "$proxy_dir/host.pid"
exec "$host_program"
