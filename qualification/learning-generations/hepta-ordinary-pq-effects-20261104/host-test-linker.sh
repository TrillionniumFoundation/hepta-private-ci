#!/bin/sh
# Optional diagnostic linker for the original Linux host library test binary.
# Keep code generation, dependencies, tests and runtime checks unchanged.
host_link_output=
host_link_want_output=0
for host_link_arg in "$@"; do
    if [ "$host_link_want_output" = 1 ]; then
        host_link_output=$host_link_arg
        host_link_want_output=0
    elif [ "$host_link_arg" = -o ]; then
        host_link_want_output=1
    fi
done

case "$host_link_output" in
    */codex_hepta_infer_worker_host-*)
        printf '%s\n' 'hepta qualification: host-test link --threads=1 --strip-debug --no-mmap-output-file' >&2
        exec /usr/bin/cc "$@" -Wl,--threads=1 -Wl,--strip-debug -Wl,--no-mmap-output-file
        ;;
    *) exec /usr/bin/cc "$@" ;;
esac
