
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/types.h>
#include <unistd.h>

extern char **environ;

static void delay_ms(long ms) {
    struct timespec t = { ms / 1000, (ms % 1000) * 1000000 };
    while (nanosleep(&t, &t) != 0 && errno == EINTR) {}
}
static int write_all(int fd, const char *p, size_t n) {
    while (n != 0) {
        ssize_t k = write(fd, p, n);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return 1;
        p += k; n -= (size_t)k;
    }
    return 0;
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (strcmp(argv[1], "blocked-stdin") == 0) {
        delay_ms(3000); return 0;
    }
    char buffer[4096];
    unsigned long total = 0;
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buffer, sizeof buffer);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return 3;
        if (n == 0) break;
        total += (unsigned long)n;
    }
    if (strcmp(argv[1], "environment") == 0) {
        size_t count = 0;
        while (environ[count] != NULL) ++count;
        const char *locale = getenv("LC_ALL");
        const char *zone = getenv("TZ");
        int isolated = count == 2 && locale != NULL && zone != NULL &&
            strcmp(locale, "C") == 0 && strcmp(zone, "UTC") == 0;
        int n = snprintf(buffer, sizeof buffer,
            "{\"isolated\":%s,\"bytes\":%lu}", isolated ? "true" : "false", total);
        if (n <= 0 || (size_t)n >= sizeof buffer) return 6;
        return write_all(STDOUT_FILENO, buffer, (size_t)n);
    }
    if (strcmp(argv[1], "descendant") == 0) {
        pid_t child = fork();
        if (child < 0) return 4;
        if (child == 0) { delay_ms(1250); _exit(0); }
    }
    if (strcmp(argv[1], "submit") == 0) return 7;
    if (strcmp(argv[1], "partial-json") == 0) {
        return write_all(STDOUT_FILENO, "{", 1);
    }
    if (strcmp(argv[1], "stdout-overrun") == 0 ||
        strcmp(argv[1], "stderr-overrun") == 0) {
        int fd = strcmp(argv[1], "stdout-overrun") == 0 ? STDOUT_FILENO : STDERR_FILENO;
        memset(buffer, 'x', sizeof buffer);
        for (int i = 0; i < 16; ++i) {
            if (write_all(fd, buffer, sizeof buffer)) return 5;
        }
        if (write_all(fd, "x", 1)) return 5;
    }
    int n = snprintf(buffer, sizeof buffer, "{\"bytes\":%lu}", total);
    if (n <= 0 || (size_t)n >= sizeof buffer) return 6;
    return write_all(STDOUT_FILENO, buffer, (size_t)n);
}
