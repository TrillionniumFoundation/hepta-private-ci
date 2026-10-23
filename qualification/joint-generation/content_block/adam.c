#include <math.h>
#include <stddef.h>

/* Same Adam element expressions as independent/native.c. Inactive groups have
 * no gradients and execute no moment, denominator or parameter update. */
int hepta_adam_blocks_v1(size_t groups, double **parameters, double **first,
                       double **second, const double **gradients,
                       const size_t *sizes, const double *first_denominator,
                       const double *second_denominator, double scale,
                       double learning_rate, int heads_only) {
    if (groups != 6 || !parameters || !first || !second || !gradients ||
        !sizes || !first_denominator || !second_denominator ||
        !isfinite(scale) || scale < 0 || scale > 1 ||
        !isfinite(learning_rate) || learning_rate <= 0 || learning_rate > 1 ||
        (heads_only != 0 && heads_only != 1)) return 1;
    for (size_t group = 0; group < groups; ++group) {
        int active = !heads_only || group >= 2;
        if (!parameters[group] || !first[group] || !second[group] ||
            sizes[group] < 1 || sizes[group] > 4000000 ||
            (active && (!gradients[group] ||
                !isfinite(first_denominator[group]) || first_denominator[group] <= 0 ||
                !isfinite(second_denominator[group]) || second_denominator[group] <= 0)) ||
            (!active && gradients[group])) return 1;
    }
    for (size_t group = 0; group < groups; ++group) {
        if (heads_only && group < 2) continue;
        for (size_t index = 0; index < sizes[group]; ++index) {
            double g = gradients[group][index] * scale;
            double m = 0.9 * first[group][index] + 0.1 * g;
            double v = 0.999 * second[group][index] + (0.001 * g) * g;
            double numerator = learning_rate * (m / first_denominator[group]);
            double denominator = sqrt(v / second_denominator[group]) + 1e-8;
            parameters[group][index] -= numerator / denominator;
            first[group][index] = m;
            second[group][index] = v;
        }
    }
    return 0;
}

/* Existing binding/ownership checks can initialize this library unchanged. */
int hepta_adam_content_v1(size_t groups, double **parameters, double **first,
                        double **second, const double **gradients,
                        const size_t *sizes, const double *first_denominator,
                        const double *second_denominator, double scale,
                        double learning_rate) {
    return hepta_adam_blocks_v1(groups, parameters, first, second, gradients,
        sizes, first_denominator, second_denominator, scale, learning_rate, 0);
}
