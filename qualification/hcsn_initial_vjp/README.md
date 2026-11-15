# Bounded initial-amplitude VJP for the finite delay equation

The physical-only bridge rejects trainable initial laws. This separate API
keeps initial active/phase probability amplitudes and arbitrary signed content
in a native Torch input graph. Physics, geometry, delay, remaining-time support
and migration stay fixed. It supplies an initial-state interface prerequisite,
not whole-network training or a combined physical/initial derivative API.

The finite marked DDE is linear in its initial measures. Its same propagator
is evaluated on up to sixteen directions at once in signed-content channels;
the auxiliary probability carrier is discarded. Torch multiplies this fixed
operator by all four live input tensors. Only safety clones are detached.
There is no detached initial-law conversion or surrogate input derivative.

`amplitude_flow` returns a tensor `[query, N+5, C+1]` and a cost receipt. Output
rows are interior active nodes, upper escape, refractory mass, events, discounted
events, discounted active time and discounted remaining-phase mass. Mark zero
is probability. Active input `[N]` omits the fixed zero lower atom and includes
upper escape; content is `[N,C]`, phase mass `[K]`, phase content `[K,C]`.

These are finite nonnegative, **unnormalized** probability amplitudes and
independent signed contents. The ambient VJP is a signed-amplitude linear
extension. Numerical two-sided tests use strictly positive probability values;
they do not treat four free blocks as a normalized probability simplex. A
physical normalized law and probability/content binding can be built explicitly
by the client, for example joint active/phase softmax weights and content equal
to probability times conditional signed marks. This chain is tested separately.
The API never silently normalizes or projects its inputs.

| Bounded check | Uniform n7 | Graded n12 |
| --- | ---: | ---: |
| Local actual-forward directional-FD maximum absolute error | 4.19e-11 | 3.39e-11 |
| Native output vs retained independent initial forward | 7.27e-12 | 6.54e-11 |
| Native full input VJP vs retained numerical operator | 1.56e-15 | 3.85e-13 |
| Native positive-amplitude projected gradcheck | passed | passed |

The local NumPy development check uses five declared directions across the
four blocks and a mixed direction, at steps 2e-4 and 1e-4, with gate
2e-7 + 2e-5*abs(FD). All seven fields are checked at 0/.13/.29/.53, including
multiple delay cycles. This is directional coverage, not an exhaustive initial
Jacobian test. It executes two basis flows and 42 direct-amplitude flows,
10.877 seconds after imports, with source-before/after guards. Git freezing
followed this local development check; it was not precommitted validation.
Its complete stderr retains a SciPy BDF invalid-subtraction warning.

The subsequent native probe was executed only after committing exact source
`372d84ed9a04cab0e1d873f9cdd534a33689b485`, its intent, command and transported
bundle. Desktop job `1a1cefd297d-2564-194e` succeeded/exit0 with complete durable
output and terminal confirmation. Python 3.12.3 / Torch 2.8.0+cu128 runs solely
on CPU, one thread; NumPy 2.3.5 / SciPy 1.17.0. Native checks execute 39 API/basis
DDE forwards and two independent uniform native-graph oracle forwards, with
zero optimizer updates. Probe wall/CPU after imports is 21.312/20.995 seconds,
peak RSS 619104 KiB. The wrapper including imports takes 26.789 seconds and
peaks at 696344 KiB. This is a bounded diagnostic cost, not model throughput.

The oracle is the unmodified finite uniform Torch cascade from #6150 tested
`19b7a99f6d63596dd77c34a1ed8e529e1c744750` (evidence
`28196265803a81d69041ad6a106e581456f3e360`). It is retained at its exact Git blob
`64b79ae441a98c351b0874d1a6cc5c8a327e0670`. The new uniform input VJP agrees
with that independent graph within 1.32e-10. The explicit client joint-softmax
and probability-times-mark graph passes projected gradcheck and agrees with
the oracle VJP within 4.20e-11. That client check retained its success flags and
maximum discrepancy, rather than separate raw normalized-gradient arrays.
The raw amplitude and uniform-oracle VJP vectors are retained. No graded
qualification is inherited from the uniform oracle.

Both normal in-place mutation and unsafe `.data` value mutation are rejected
for all four initial inputs; those eight checks execute on the uniform fixture
through the common wrapper. The old physical-only API still refuses a
trainable prior. This wrapper is first-order only; checkpoint AD, phase support,
delay, migration, filtering and physical-parameter gradients are not supplied.

Admission is explicitly small: N<=32, K<=8, C<=4, at most five queries within
min(.6,3*delay), forty directions and 7400 operator scalars. A forward needs at
most three small basis flows. There is no cache, n512 scalability claim or
adjoint implementation. An adjoint requires its own endpoint/jump and
time-dependent-discount validation against these retained small references.

All NumPy originals, exact precommitted native source/intent, thirteen guarded
source identities, original native arrays, calls, stdout/stderr and file hashes
are retained. The first inline command was rejected by the 64KiB source limit;
its timeout and same-key validation rejection are preserved. The valid v2 uses
create-only binary transport and a short launcher. Large archive reads timed
out; complete small original files and the native NPZ were recovered instead.
Reassembly reproduces the original native archive exactly: 145125 bytes,
SHA256 `6d95ecb448ad3cf5afb1f2b5a11bae314c8d6f4ff12f4634582648c6513f6dd1`.
No model was replayed for recovery.

An independent inspector imports no candidate or Torch. It reproduces all
3480 directional-FD comparisons, all 69 native raw input-VJP coordinates,
the uniform oracle comparison, source/format/file identities and call counts.
The normalized-chain comparison is derived from the retained linear VJPs,
rather than misrepresented as a separate native normalized-gradient readback.
Its two arithmetic executions add zero ODE/kernel/Torch/optimizer calls.
Four owned modules were finally Ruff-formatted and `just fmt` passed;
all thirteen numerical source ASTs remain identical to their actual tested
bytes. No local tests or model runs followed formatting.

Global status remains **Draft / HOLD / all_closed=false**. The evidence concerns
two disclosed fixed-physics small meshes, supported initial amplitudes and
projected derivatives. It does not qualify all initial laws/physics, v3,
large-grid initial gradients, continuum accuracy, observation filtering,
whole-network training, C2 recovery, independent tasks, energy or adoption.
