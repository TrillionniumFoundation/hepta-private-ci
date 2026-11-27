/* Separate four-group ABI. Original Adam arithmetic; no fast-math/FMA. */
#include <math.h>
#include <stddef.h>

int hepta_adam_semantic4_v1(size_t groups, double **parameters, double **first,
                           double **second, const double **gradients,
                           const size_t *sizes, const double *denom1,
                           const double *denom2, double scale, double lr) {
    if (groups != 4 || !parameters || !first || !second || !gradients ||
        !sizes || !denom1 || !denom2 || !isfinite(scale) || scale < 0.0 ||
        scale > 1.0 || !isfinite(lr) || lr <= 0.0 || lr > 1.0) return 1;
    for (size_t g = 0; g < groups; ++g) {
        if (!parameters[g] || !first[g] || !second[g] || !gradients[g] ||
            sizes[g] < 1 || sizes[g] > 4000000 || !isfinite(denom1[g]) ||
            denom1[g] <= 0.0 || !isfinite(denom2[g]) || denom2[g] <= 0.0)
            return 1;
    }
    for (size_t g = 0; g < groups; ++g) {
        for (size_t j = 0; j < sizes[g]; ++j) {
            double vgrad = gradients[g][j] * scale;
            double m = 0.9 * first[g][j] + 0.1 * vgrad;
            double v = 0.999 * second[g][j] + (0.001 * vgrad) * vgrad;
            double numerator = lr * (m / denom1[g]);
            double denominator = sqrt(v / denom2[g]) + 1e-8;
            parameters[g][j] -= numerator / denominator;
            first[g][j] = m;
            second[g][j] = v;
        }
    }
    return 0;
}
