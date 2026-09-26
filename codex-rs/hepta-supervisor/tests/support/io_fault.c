/* Linux qualification-only interposer. Loaded only into a disposable daemon.
 * A one-shot control file selects one test-owned run root and real errno cut.
 * It never fills disks, changes mounts, or modifies the production executable.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <fcntl.h>

static int inject(int fd, int syncing) {
    const char *control = getenv("HEPTA_QUAL_IO_FAULT_CONTROL");
    if (!control || strncmp(control, "/tmp/hsq-", 9) != 0) return 0;
    int config_fd = (int)syscall(SYS_openat, AT_FDCWD, control, O_RDONLY | O_CLOEXEC | O_NOFOLLOW, 0);
    if (config_fd < 0) return 0;
    char config[PATH_MAX + 64];
    ssize_t length = syscall(SYS_read, config_fd, config, sizeof(config) - 1);
    syscall(SYS_close, config_fd);
    if (length <= 0) return 0;
    config[length] = '\0';
    char *root = strchr(config, '\n');
    if (!root) return 0;
    *root++ = '\0';
    char *end = strchr(root, '\n');
    if (!end) return 0;
    *end = '\0';
    if (strncmp(root, "/tmp/hsq-", 9) != 0) return 0;
    char descriptor[64], path[PATH_MAX + 1], hit[PATH_MAX + 1];
    int printed = snprintf(descriptor, sizeof(descriptor), "/proc/self/fd/%d", fd);
    if (printed <= 0 || (size_t)printed >= sizeof(descriptor)) return 0;
    ssize_t size = syscall(SYS_readlink, descriptor, path, sizeof(path) - 1);
    if (size <= 0) return 0;
    path[size] = '\0';
    size_t root_size = strlen(root);
    if (strncmp(path, root, root_size) != 0) return 0;
    int error = 0;
    if (syncing && strcmp(config, "fsync_eio") == 0 && path[root_size] == '\0') {
        error = EIO; /* Parent sync after atomic publication. */
    } else if (!syncing && strcmp(config, "write_enospc") == 0 && path[root_size] == '/') {
        const char *name = path + root_size + 1;
        if (strncmp(name, ".supervisor", 11) == 0) error = ENOSPC;
    }
    if (!error) return 0;
    printed = snprintf(hit, sizeof(hit), "%s.hit", control);
    if (printed <= 0 || (size_t)printed >= sizeof(hit)) return 0;
    /* Rename consumes the trigger once even with concurrent writers. */
    if (syscall(SYS_rename, control, hit) != 0) return 0;
    return error;
}

int fsync(int fd) {
    int saved = errno;
    int error = inject(fd, 1);
    if (error) { errno = error; return -1; }
    int (*next)(int) = dlsym(RTLD_NEXT, "fsync");
    if (!next) { errno = ENOSYS; return -1; }
    errno = saved;
    return next(fd);
}

ssize_t write(int fd, const void *buffer, size_t count) {
    int saved = errno;
    int error = inject(fd, 0);
    if (error) { errno = error; return -1; }
    ssize_t (*next)(int, const void *, size_t) = dlsym(RTLD_NEXT, "write");
    if (!next) { errno = ENOSYS; return -1; }
    errno = saved;
    return next(fd, buffer, count);
}
