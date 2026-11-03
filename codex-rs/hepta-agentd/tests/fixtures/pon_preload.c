
#include <stdio.h>
#include <stdlib.h>
__attribute__((constructor)) static void injected(void) {
    const char *path = getenv("HEPTA_PON_TEST_MARKER");
    if (path == NULL) return;
    FILE *file = fopen(path, "wb");
    if (file != NULL) { fputs("loaded", file); fclose(file); }
}
