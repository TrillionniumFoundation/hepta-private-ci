/* Bounded double-precision content/continuation kernels, without fast-math.
 * Array ownership, lengths, finite parameters and input domains are validated
 * by native.py. Return 1 for invalid ABI arguments and 2 for nonfinite results.
 */
#include <math.h>
#include <stddef.h>

static int softmax12(double *values) {
    double maximum = values[0];
    double total = 0.0;
    for (int k = 0; k < 12; ++k) {
        if (!isfinite(values[k])) return 2;
        if (values[k] > maximum) maximum = values[k];
    }
    for (int k = 0; k < 12; ++k) {
        values[k] = exp(values[k] - maximum);
        total += values[k];
    }
    if (!isfinite(total) || total <= 0.0) return 2;
    for (int k = 0; k < 12; ++k) values[k] /= total;
    return 0;
}

static int forward_state(const double *x, size_t n, int hidden, int low,
                         const double *encoder, const double *bias,
                         const double *text, const double *text_bias,
                         const double *image, const double *image_bias,
                         double *p, double *q, double *hidden_out) {
    if (!x || !encoder || !bias || !text || !text_bias || !image ||
        !image_bias || !p || !q || n < 1 || n > 65536 ||
        hidden < 1 || hidden > 512 || (low != 0 && low != 1)) return 1;
    for (size_t row = 0; row < n; ++row) {
        const double *input = x + row * 202;
        double packed[58];
        double state[512] = {0.0};
        double *pt = p + row * 12;
        double *pi = q + row * 12;
        int dimension = 202;
        if (low) {
            for (int by = 0; by < 4; ++by) {
                for (int bx = 0; bx < 4; ++bx) {
                    for (int channel = 0; channel < 3; ++channel) {
                        int index = ((2 * by) * 8 + 2 * bx) * 3 + channel;
                        packed[(by * 4 + bx) * 3 + channel] =
                            ((input[index] + input[index + 3]) +
                             (input[index + 24] + input[index + 27])) / 4.0;
                    }
                }
            }
            for (int j = 0; j < 10; ++j) packed[48 + j] = input[192 + j];
            input = packed;
            dimension = 58;
        }
        /* Contiguous weight rows allow vectorization across independent units. */
        for (int i = 0; i < dimension; ++i) {
            const double *weights = encoder + (size_t)i * hidden;
            for (int j = 0; j < hidden; ++j) state[j] += input[i] * weights[j];
        }
        for (int j = 0; j < hidden; ++j) {
            state[j] = tanh(state[j] + bias[j]);
            if (!isfinite(state[j])) return 2;
        }
        if (hidden_out)
            for (int j = 0; j < hidden; ++j)
                hidden_out[row * (size_t)hidden + j] = state[j];
        for (int k = 0; k < 12; ++k) pt[k] = pi[k] = 0.0;
        for (int j = 0; j < hidden; ++j) {
            for (int k = 0; k < 12; ++k) {
                pt[k] += state[j] * text[(size_t)j * 12 + k];
                pi[k] += state[j] * image[(size_t)j * 12 + k];
            }
        }
        for (int k = 0; k < 12; ++k) {
            pt[k] += text_bias[k];
            pi[k] += image_bias[k];
        }
        int status = softmax12(pt);
        if (status) return status;
        status = softmax12(pi);
        if (status) return status;
    }
    return 0;
}

int hepta_forward(const double *x, size_t n, int hidden, int low,
                  const double *encoder, const double *bias,
                  const double *text, const double *text_bias,
                  const double *image, const double *image_bias,
                  double *p, double *q) {
    return forward_state(x, n, hidden, low, encoder, bias, text, text_bias,
                         image, image_bias, p, q, NULL);
}

/* hidden_out is a required row-major n-by-hidden post-tanh output. */
int hepta_forward_state_v1(const double *x, size_t n, int hidden, int low,
                           const double *encoder, const double *bias,
                           const double *text, const double *text_bias,
                           const double *image, const double *image_bias,
                           double *p, double *q, double *hidden_out) {
    if (!hidden_out) return 1;
    return forward_state(x, n, hidden, low, encoder, bias, text, text_bias,
                         image, image_bias, p, q, hidden_out);
}

int hepta_low_critic(const double *x, int hidden, const double *encoder58,
                     const double *bias, const double *text,
                     const double *text_bias, const double *image,
                     const double *image_bias, const double *mean31,
                     const double *scale31, const double *weights31,
                     double intercept, double lower, double upper,
                     double *p12, double *q12, double *gain1) {
    if (!mean31 || !scale31 || !weights31 || !gain1 ||
        !isfinite(intercept) || !isfinite(lower) || !isfinite(upper) ||
        lower > upper) return 1;
    for (int j = 0; j < 31; ++j) {
        if (!isfinite(mean31[j]) || !isfinite(scale31[j]) ||
            !isfinite(weights31[j]) || scale31[j] <= 0.0) return 1;
    }
    int status = hepta_forward(x, 1, hidden, 1, encoder58, bias, text,
                               text_bias, image, image_bias, p12, q12);
    if (status) return status;
    double features[31];
    for (int k = 0; k < 12; ++k) {
        features[k] = p12[k];
        features[12 + k] = q12[k];
    }
    for (int modality = 0; modality < 2; ++modality) {
        const double *values = modality ? q12 : p12;
        double entropy = 0.0;
        double first = -INFINITY;
        double second = -INFINITY;
        for (int k = 0; k < 12; ++k) {
            double probability = values[k];
            entropy -= probability * log(fmax(probability, 1e-300));
            if (probability >= first) {
                second = first;
                first = probability;
            } else if (probability > second) {
                second = probability;
            }
        }
        features[24 + modality * 3] = entropy / log(12.0);
        features[25 + modality * 3] = first - second;
        features[26 + modality * 3] = first;
    }
    double overlap = 0.0;
    for (int k = 0; k < 12; ++k) overlap += p12[k] * q12[k];
    features[30] = overlap;
    double gain = 0.0;
    for (int j = 0; j < 31; ++j)
        gain += ((features[j] - mean31[j]) / scale31[j]) * weights31[j];
    gain += intercept;
    if (isnan(gain)) return 2;
    if (gain < lower) gain = lower;
    if (gain > upper) gain = upper;
    *gain1 = gain;
    return 0;
}

int hepta_batch(const double *x, size_t n, int hidden, int mode,
                const double *encoder202, const double *encoder58,
                const double *bias, const double *text, const double *text_bias,
                const double *image, const double *image_bias,
                const double *mean31, const double *scale31, const double *weights31,
                double intercept, double lower, double upper, double price,
                const unsigned char *random_full_mask, double *p, double *q,
                double *gains, int *low_used, int *full_used) {
    if (!x || !bias || !text || !text_bias || !image || !image_bias ||
        !p || !q || !gains || !low_used || !full_used || n < 1 || n > 65536 ||
        hidden < 1 || hidden > 512 || mode < 0 || mode > 4 ||
        !isfinite(price) || price < 0.0) return 1;
    if (mode != 1 && mode != 4 && !encoder202) return 1;
    if (mode != 0 && mode != 4 && !encoder58) return 1;
    if (mode == 3 && (!mean31 || !scale31 || !weights31)) return 1;
    if (mode == 4) {
        if (!random_full_mask) return 1;
        for (size_t row = 0; row < n; ++row)
            if (random_full_mask[row] > 1 || (random_full_mask[row] ? !encoder202 : !encoder58)) return 1;
    }
    for (size_t row = 0; row < n; ++row) {
        const double *input = x + row * 202;
        double *pt = p + row * 12, *pi = q + row * 12;
        double full_p[12], full_q[12];
        int status;
        gains[row] = 0.0;
        low_used[row] = full_used[row] = 0;
        if (mode == 0 || (mode == 4 && random_full_mask[row])) {
            status = hepta_forward(input, 1, hidden, 0, encoder202, bias,
                                    text, text_bias, image, image_bias, pt, pi);
            if (status) return status;
            full_used[row] = 1;
            continue;
        }
        if (mode == 3)
            status = hepta_low_critic(input, hidden, encoder58, bias, text,
                text_bias, image, image_bias, mean31, scale31, weights31,
                intercept, lower, upper, pt, pi, gains + row);
        else
            status = hepta_forward(input, 1, hidden, 1, encoder58, bias,
                                    text, text_bias, image, image_bias, pt, pi);
        if (status) return status;
        low_used[row] = 1;
        if (mode == 2 || (mode == 3 && gains[row] > price)) {
            status = hepta_forward(input, 1, hidden, 0, encoder202, bias,
                         text, text_bias, image, image_bias, full_p, full_q);
            if (status) return status;
            full_used[row] = 1;
            for (int k = 0; k < 12; ++k) {
                pt[k] = mode == 2 ? (pt[k] + full_p[k]) / 2.0 : full_p[k];
                pi[k] = mode == 2 ? (pi[k] + full_q[k]) / 2.0 : full_q[k];
            }
        }
    }
    return 0;
}

/* Affine continuation features are [low post-tanh state, instruction10]. */
int hepta_batch_gain_v1(const double *x, size_t n, int hidden,
                        const double *encoder202, const double *encoder58,
                        const double *bias, const double *text,
                        const double *text_bias, const double *image,
                        const double *image_bias, const double *mean,
                        const double *scale, const double *weights,
                        double intercept, double lower, double upper,
                        double price, double *p, double *q, double *gains,
                        int *low_used, int *full_used) {
    if (!x || !encoder202 || !encoder58 || !bias || !text || !text_bias ||
        !image || !image_bias || !mean || !scale || !weights || !p || !q ||
        !gains || !low_used || !full_used || n < 1 || n > 65536 ||
        hidden < 1 || hidden > 512 || !isfinite(intercept) ||
        !isfinite(lower) || !isfinite(upper) || lower > upper ||
        !isfinite(price) || price < 0.0) return 1;
    int dimension = hidden + 10;
    for (int j = 0; j < dimension; ++j) {
        if (!isfinite(mean[j]) || !isfinite(scale[j]) ||
            !isfinite(weights[j]) || scale[j] <= 0.0) return 1;
    }
    for (size_t row = 0; row < n; ++row) {
        const double *input = x + row * 202;
        double *pt = p + row * 12, *pi = q + row * 12;
        double state[512];
        double gain = 0.0;
        gains[row] = 0.0;
        low_used[row] = full_used[row] = 0;
        int status = forward_state(input, 1, hidden, 1, encoder58, bias,
            text, text_bias, image, image_bias, pt, pi, state);
        if (status) return status;
        low_used[row] = 1;
        for (int j = 0; j < dimension; ++j) {
            double feature = j < hidden ? state[j] : input[192 + j - hidden];
            if (!isfinite(feature)) return 2;
            gain += ((feature - mean[j]) / scale[j]) * weights[j];
        }
        gain += intercept;
        if (!isfinite(gain)) return 2;
        if (gain < lower) gain = lower;
        if (gain > upper) gain = upper;
        gains[row] = gain;
        if (gain > price) {
            status = hepta_forward(input, 1, hidden, 0, encoder202, bias,
                text, text_bias, image, image_bias, pt, pi);
            if (status) return status;
            full_used[row] = 1;
        }
    }
    return 0;
}
