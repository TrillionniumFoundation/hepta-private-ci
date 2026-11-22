#!/bin/sh
set -eu

printf 'schema=hcsn-index1159-current-resource-observation-v1\n'
printf 'sample_utc='
date -u +%Y-%m-%dT%H:%M:%SZ
printf 'boot_id='
cat /proc/sys/kernel/random/boot_id
printf 'kernel='
uname -srmo
printf 'self_cgroup='
awk -F: '$1=="0"{print $3}' /proc/self/cgroup
awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree):/{print "meminfo_" $1 "=" $2 " " $3}' /proc/meminfo
printf 'memory_pressure='
tr '\n' ';' < /proc/pressure/memory
printf '\n'

cg_path=$(awk -F: '$1=="0"{print $3}' /proc/self/cgroup)
current_path="/sys/fs/cgroup$cg_path"
level=0
while [ "$current_path" != "/sys/fs" ] && [ "$current_path" != "/" ]; do
  printf 'cgroup_level=%s path=%s\n' "$level" "$current_path"
  for field in \
    memory.current memory.peak memory.min memory.low memory.high memory.max \
    memory.swap.current memory.swap.max memory.events pids.current pids.max \
    cpu.max cpuset.cpus.effective
  do
    if [ -r "$current_path/$field" ]; then
      value=$(tr '\n' ';' < "$current_path/$field")
      printf 'cgroup_field=%s value=%s\n' "$field" "$value"
    fi
  done
  current_path=$(dirname "$current_path")
  level=$((level + 1))
done

printf 'nproc='
getconf _NPROCESSORS_ONLN
printf 'page_size='
getconf PAGESIZE
