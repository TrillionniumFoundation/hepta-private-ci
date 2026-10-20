/* Deterministic Linux configuration for D-Bus 1.16.2's client library.
 * Features below are supported by both the pinned glibc and musl toolchains.
 * Runtime paths are D-Bus defaults, never compiler or linker search paths.
 */
#ifndef HEPTA_DBUS_CONFIG_H
#define HEPTA_DBUS_CONFIG_H

#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#if !defined(__linux__) || (!defined(__x86_64__) && !defined(__aarch64__)) || \
    __SIZEOF_POINTER__ != 8 || __SIZEOF_LONG__ != 8
#error "The hermetic libdbus configuration supports Linux x86_64/aarch64 LP64 only"
#endif
/* Linux UAPI syscall numbers agree on both supported architectures. Older
 * toolchain headers omit these; the running kernel still decides availability.
 * See Linux v6.18 syscall_64.tbl and include/uapi/asm-generic/unistd.h.
 */
#include <sys/syscall.h>
#ifndef __NR_pidfd_open
#define __NR_pidfd_open 434
#endif
#ifndef SYS_pidfd_open
#define SYS_pidfd_open __NR_pidfd_open
#endif
#ifndef __NR_close_range
#define __NR_close_range 436
#endif
#ifndef CLOSE_RANGE_CLOEXEC
#define CLOSE_RANGE_CLOEXEC (1U << 2)
#endif
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
#define WORDS_BIGENDIAN 1
#endif
#define VERSION "1.16.2"
#define DBUS_UNIX 1
#define DBUS_ENABLE_ASSERT 1
#define DBUS_ENABLE_CHECKS 1
#define DBUS_USE_SYNC 1
#define DBUS_SESSION_BUS_CONNECT_ADDRESS "autolaunch:"
#define DBUS_SYSTEM_BUS_DEFAULT_ADDRESS "unix:path=/run/dbus/system_bus_socket"
#define DBUS_SESSION_SOCKET_DIR "/tmp"
#define DBUS_MACHINE_UUID_FILE "/var/lib/dbus/machine-id"
#define DBUS_RUNSTATEDIR "/run"
#define DBUS_BINDIR "/usr/bin"
#define DBUS_PREFIX "/usr"
#define DBUS_CONSOLE_OWNER_FILE "/var/run/console/console.lock"
#define HAVE_ACCEPT4 1
#define HAVE_ALLOCA_H 1
#define HAVE_BYTESWAP_H 1
#define HAVE_CLEARENV 1
#define HAVE_DECL_ENVIRON 1
#define HAVE_DECL_MSG_NOSIGNAL 1
#define HAVE_DECL_LOG_PERROR 1
#define HAVE_DECL_SYS_PIDFD_OPEN 1
#define HAVE_DIRENT_H 1
#define HAVE_ERRNO_H 1
#define HAVE_FSTATFS 1
#define HAVE_GETGROUPLIST 1
#define HAVE_GETPWNAM_R 1
#define HAVE_GETRANDOM 1
#define HAVE_GETRESUID 1
#define HAVE_INTTYPES_H 1
#define HAVE_LINUX_MAGIC_H 1
#define HAVE_LOCALE_H 1
#define HAVE_LOCALECONV 1
#define HAVE_MONOTONIC_CLOCK 1
#define HAVE_NANOSLEEP 1
#define HAVE_PIPE2 1
#define HAVE_POLL 1
#define HAVE_SETENV 1
#define HAVE_SETLOCALE 1
#define HAVE_SIGNAL_H 1
#define HAVE_SOCKETPAIR 1
#define HAVE_SOCKLEN_T 1
#define HAVE_STDATOMIC_H 1
#define HAVE_STDIO_H 1
#define HAVE_SYSLOG_H 1
#define HAVE_SYS_RANDOM_H 1
#define HAVE_SYS_SYSCALL_H 1
#define HAVE_SYS_TIME_H 1
#define HAVE_SYS_VFS_H 1
#define HAVE_UNISTD_H 1
#define HAVE_UNIX_FD_PASSING 1
#define HAVE_UNSETENV 1
#define HAVE_WRITEV 1

#endif
