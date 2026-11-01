/* Independent research CTMC executor, not a production Hepta runtime.
 * Input (stdin, or --input FILE): n dt, then n initial probabilities, then
 * n*n entries of the row generator Q.  Output: one JSON record.
 * Build: cc -std=c11 -O2 -Wall -Wextra -pedantic native_probe.c -lm -o probe
 * Run: probe --float64  or  probe --float32
 * Both variants use actual arithmetic of the named type, without probability
 * renormalization, positivity projection or a hidden double matrix kernel.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_STATES 512

/* Splitting bounds every Poisson mean by eight.  The geometric upper bound
 * controls the omitted tail independently of the accumulated floating sum. */
#define DEFINE_PROPAGATOR(NAME, TYPE, EXP, CEIL, EPSILON)                       \
static int NAME(int n, TYPE dt, const TYPE *qmat, TYPE *state,                 \
                int *substeps, long *terms) {                                \
    TYPE rate = (TYPE)0;                                                      \
    for (int i = 0; i < n; ++i) {                                            \
        if (-qmat[i*n+i] > rate) rate = -qmat[i*n+i];                         \
    }                                                                        \
    *substeps = 0; *terms = 0;                                                \
    if (rate == (TYPE)0 || dt == (TYPE)0) return 0;                           \
    TYPE pieces = CEIL(rate * dt / (TYPE)8);                                 \
    if (!isfinite(pieces) || pieces > (TYPE)1000000) return 2;                \
    *substeps = pieces < (TYPE)1 ? 1 : (int)pieces;                           \
    TYPE mu = rate * (dt / (TYPE)*substeps);                                 \
    TYPE *p = malloc((size_t)n*n*sizeof(TYPE));                               \
    TYPE *power = malloc((size_t)n*sizeof(TYPE));                             \
    TYPE *next = malloc((size_t)n*sizeof(TYPE));                              \
    TYPE *sum = malloc((size_t)n*sizeof(TYPE));                               \
    if (!p || !power || !next || !sum) {                                     \
        free(p); free(power); free(next); free(sum); return 3;                \
    }                                                                        \
    for (int i = 0; i < n; ++i) {                                            \
        for (int j = 0; j < n; ++j) {                                        \
            p[i*n+j] = qmat[i*n+j] / rate;                                  \
            if (i == j) p[i*n+j] += (TYPE)1;                                \
        }                                                                    \
    }                                                                        \
    int status = 0;                                                          \
    for (int step = 0; step < *substeps; ++step) {                            \
        TYPE weight = EXP(-mu);                                             \
        for (int i = 0; i < n; ++i) {                                        \
            power[i] = state[i];                                            \
            sum[i] = weight * state[i];                                     \
        }                                                                    \
        int converged = 0;                                                  \
        for (int k = 1; k <= 4096; ++k) {                                    \
            for (int j = 0; j < n; ++j) {                                    \
                TYPE value = (TYPE)0;                                       \
                for (int i = 0; i < n; ++i)                                 \
                    value += power[i] * p[i*n+j];                            \
                next[j] = value;                                            \
            }                                                                \
            memcpy(power, next, (size_t)n*sizeof(TYPE));                     \
            weight *= mu / (TYPE)k;                                         \
            for (int j = 0; j < n; ++j) sum[j] += weight * power[j];         \
            ++*terms;                                                       \
            if ((TYPE)(k+2) > mu) {                                         \
                TYPE tail = weight * (mu / (TYPE)(k+1))                     \
                    / ((TYPE)1 - mu / (TYPE)(k+2));                          \
                if (tail < (TYPE)(EPSILON)) { converged = 1; break; }        \
            }                                                                \
        }                                                                    \
        if (!converged) { status = 4; break; }                               \
        memcpy(state, sum, (size_t)n*sizeof(TYPE));                           \
    }                                                                        \
    free(p); free(power); free(next); free(sum);                              \
    return status;                                                          \
}

DEFINE_PROPAGATOR(propagate64, double, exp, ceil, 2e-17)
DEFINE_PROPAGATOR(propagate32, float, expf, ceilf, 2e-9f)

int main(int argc, char **argv) {
    int use_float = 0;
    const char *path = NULL;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--float32")) use_float = 1;
        else if (!strcmp(argv[i], "--float64")) use_float = 0;
        else if (!strcmp(argv[i], "--input") && i+1 < argc) path = argv[++i];
        else { fprintf(stderr, "usage: probe [--float32|--float64] [--input FILE]\n"); return 1; }
    }
    clock_t start = clock();
    FILE *input = path ? fopen(path, "r") : stdin;
    if (!input) { perror("input"); return 1; }
    int n;
    double dt;
    if (fscanf(input, "%d %lf", &n, &dt) != 2 || n < 1 || n > MAX_STATES
            || !isfinite(dt) || dt < 0) {
        fprintf(stderr, "invalid dimension or duration\n"); return 1;
    }
    double *state = calloc((size_t)n, sizeof(double));
    double *qmat = calloc((size_t)n*n, sizeof(double));
    if (!state || !qmat) { fprintf(stderr, "allocation failure\n"); return 1; }
    double mass = 0;
    for (int i = 0; i < n; ++i) {
        if (fscanf(input, "%lf", &state[i]) != 1 || !isfinite(state[i]) || state[i] < 0) {
            fprintf(stderr, "invalid initial distribution\n"); return 1;
        }
        mass += state[i];
    }
    if (fabs(mass-1) > 1e-9) { fprintf(stderr, "initial mass is not one\n"); return 1; }
    for (int i = 0; i < n; ++i) {
        double row = 0;
        for (int j = 0; j < n; ++j) {
            if (fscanf(input, "%lf", &qmat[i*n+j]) != 1 || !isfinite(qmat[i*n+j])
                    || (i != j && qmat[i*n+j] < 0)) {
                fprintf(stderr, "invalid generator entry\n"); return 1;
            }
            row += qmat[i*n+j];
        }
        if (qmat[i*n+i] > 0 || fabs(row) > 1e-10*fmax(1, -qmat[i*n+i])) {
            fprintf(stderr, "generator row does not conserve mass\n"); return 1;
        }
    }
    if (path) fclose(input);
    int substeps = 0;
    long terms = 0;
    int status;
    if (use_float) {
        float *q32 = malloc((size_t)n*n*sizeof(float));
        float *p32 = malloc((size_t)n*sizeof(float));
        if (!q32 || !p32) { fprintf(stderr, "allocation failure\n"); return 1; }
        for (int i = 0; i < n*n; ++i) q32[i] = (float)qmat[i];
        for (int i = 0; i < n; ++i) p32[i] = (float)state[i];
        status = propagate32(n, (float)dt, q32, p32, &substeps, &terms);
        for (int i = 0; i < n; ++i) state[i] = (double)p32[i];
        free(q32); free(p32);
    } else status = propagate64(n, dt, qmat, state, &substeps, &terms);
    if (status) {
        fprintf(stderr, "uniformization failed with status %d\n", status);
        free(state); free(qmat); return status;
    }
    double cpu = (double)(clock()-start) / CLOCKS_PER_SEC;
    mass = 0;
    double minimum = state[0];
    for (int i = 0; i < n; ++i) {
        if (!isfinite(state[i])) { fprintf(stderr, "nonfinite output\n"); return 5; }
        mass += state[i];
        if (state[i] < minimum) minimum = state[i];
    }
    printf("{\"dtype\":\"%s\",\"substeps\":%d,\"poisson_terms\":%ld,"
           "\"cpu_seconds\":%.9g,\"mass\":%.17g,\"minimum\":%.17g,\"state\":[",
           use_float ? "float32" : "float64", substeps, terms, cpu, mass, minimum);
    for (int i = 0; i < n; ++i) printf("%s%.17g", i ? "," : "", state[i]);
    printf("]}\n");
    free(state); free(qmat);
    return 0;
}
