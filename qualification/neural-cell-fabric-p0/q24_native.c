/* Reviewed fixed AOT dot16 research primitive: no JIT, syscalls, pointers from models or UI effects. */
#include <stdint.h>
#include <stddef.h>
#define SCALE ((int64_t)1 << 24)
#define LIMIT ((int64_t)8 << 24)
/* Return 0 on success, -1 for invalid inputs. Only caller-owned 16-lane buffers. */
int hepta_q24_dot16(const int32_t *features, const int32_t *weights, uint32_t lanes, int64_t *out) {
    if (!features || !weights || !out || lanes == 0 || lanes > 16) return -1;
    int64_t acc = 0;
    for (uint32_t i = 0; i < lanes; ++i) {
        if (features[i] > LIMIT || features[i] < -LIMIT ||
            weights[i] > LIMIT || weights[i] < -LIMIT) return -1;
        /* Each product <= (8*2^24)^2, 16 terms fit signed int64. */
        acc += (int64_t)features[i] * (int64_t)weights[i];
    }
    uint64_t absval = (uint64_t)(acc < 0 ? -acc : acc);
    uint64_t whole = absval / (uint64_t)SCALE;
    uint64_t remain = absval % (uint64_t)SCALE;
    if (2 * remain > (uint64_t)SCALE ||
        (2 * remain == (uint64_t)SCALE && (whole & 1u))) ++whole;
    *out = acc < 0 ? -(int64_t)whole : (int64_t)whole;
    return 0;
}
