/* Fixed ABI configuration for the repository's Linux LP64 targets. */
#ifndef DBUS_ARCH_DEPS_H
#define DBUS_ARCH_DEPS_H

#include <dbus/dbus-macros.h>

#if !defined(__linux__) || (!defined(__x86_64__) && !defined(__aarch64__)) || \
    __SIZEOF_POINTER__ != 8 || __SIZEOF_LONG__ != 8
#error "The hermetic libdbus configuration supports Linux x86_64/aarch64 LP64 only"
#endif

DBUS_BEGIN_DECLS
#define DBUS_HAVE_INT64 1
typedef long dbus_int64_t;
typedef unsigned long dbus_uint64_t;
#define DBUS_INT64_MODIFIER "l"
#define DBUS_INT64_CONSTANT(val) (val##L)
#define DBUS_UINT64_CONSTANT(val) (val##UL)
typedef int dbus_int32_t;
typedef unsigned int dbus_uint32_t;
typedef short dbus_int16_t;
typedef unsigned short dbus_uint16_t;
#define DBUS_SIZEOF_VOID_P 8
#define DBUS_MAJOR_VERSION 1
#define DBUS_MINOR_VERSION 16
#define DBUS_MICRO_VERSION 2
#define DBUS_VERSION_STRING "1.16.2"
#define DBUS_VERSION ((1 << 16) | (16 << 8) | 2)
DBUS_END_DECLS

#endif
