#include <math.h>
#include <stddef.h>

void normal_cdf(const double *values, double *output, size_t count) {
    const double scale = -1.0 / sqrt(2.0);
    for (size_t i = 0; i < count; ++i) {
        output[i] = 0.5 * erfc(values[i] * scale);
    }
}
