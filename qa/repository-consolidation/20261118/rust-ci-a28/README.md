# Guardian fixture repairs and closed-receiver PTY draining

This checkpoint follows the real Notes merge at
`342b284c1514da3d3d8b6451b6bd3fb6edfc783a`. It changes two Core integration-test
files and five lines in the PTY reader. All three original file blobs in that
parent are identical to the `a91102d3639a5a1f02394bfc0331611e9ab101a1` inputs used
for the component qualification below.

## Guardian network response routing

The old fixture assigned three HTTP responses in arrival order. After the first
one-second execution yield, a slower network request lets the parent session
arrive before Guardian and consume the response intended for Guardian. A
diagnostic control adds only two seconds before the original command: the
original exact-trigger assertion fails with an empty list in 1.415 seconds.

The repaired fixture uses the existing request-identity routing helper. The
parent's final response waits for the original execution's real terminal event.
That event follows process exit, output draining, and the network-denial monitor;
it is distinct from the first execution yield. The fixture still requires the
original call identifier, complete command, and exactly three model requests.

Two selected native cases pass: immediate execution in 0.436 seconds, and a
network request explicitly released after the parent receives the first yield
in 1.557 seconds. Review and turn completion retain a ten-second total budget.
Core production code is unchanged by this repair.

## Guardian multimodal test registration

The locked Tokio macro first converts the async function into a synchronous test
wrapper. With its former position above the sixteen parameter attributes, the
parameter macro then adds another test registration to that same wrapper. A
real listing of one frozen native test binary proves 32 registrations for only
16 distinct names, with every name present twice.

Moving the single Tokio attribute below the sixteen parameter attributes keeps
the original async function available to the parameter macro. A fresh binary
lists exactly the same sixteen distinct names, each once. All sixteen original
parameter vectors and the entire function body remain byte-identical. Valid and
invalid images, the large malformed-image case, privacy and fallback assertions,
and the original ten-second limit remain in place.

All sixteen native cases pass with zero retries, in 10.850 seconds total. The
Node and computer-use multimodal cases take 1.303 and 1.312 seconds. This is a
correction of duplicate registrations; it does not discard a distinct original
test case.

The native harness uses actual compiled and frozen standard-I/O and CodeMode
helper binaries. Earlier missing metadata, a shared helper replacement caught
by its SHA check, and the shell's removal of a hyphenated environment key remain
recorded as setup failures. The successful run uses the existing supported
underscore alias. These setup failures are not presented as product failures or
as passing tests.

## Continue PTY draining after the output receiver closes

The reader now checks whether its output receiver has closed before allocating
and attempting to send a discarded message. It continues reading the original
PTY until the existing EOF or error condition. Interrupted-read retry, the
bounded send while the receiver is open, and child lifetime are unchanged.

On macOS 26.6.2 ARM64 with Rust 1.96.0, the complete original PTY project command
passes all 30 cases both before and after this five-line patch, with zero skips
or retries and identical case-name sets. The original dropped-receiver case
still writes 4 MiB, waits two seconds, sets its ten-second child alarm, and
requires exit code zero. The baseline already passes on this ARM machine, so
these results do not establish that the original Intel CI failure is fixed or
that runtime performance improved.

The production change comes from ordinary commit `8075eb3`. Its two old
diagnostic-only lines are excluded because their diagnostics subsystem is absent
from this source. The branch's 268 outstanding commits have extensive independent
merge conflicts; no parent from that branch is attached by this small repair.

## Maintenance, evidence, and remaining gates

The Core scoped `just fix -p codex-core --offline --locked` and original `just fmt`
complete successfully after the tests. The multimodal file is unchanged by
formatting; the network fixture has only the recorded Rust formatter layout
changes. The PTY `just fmt` also completes without changing tested bytes. No
tests run after these maintenance steps.

The two original archives retain 62 Core evidence files plus their member
manifest (63 regular files total), and 37 PTY files, including the original
failed attempts, successful logs, source snapshots, tool identities,
registration listings, and maintenance records. `evidence-index.json` binds every
regular member to its size and SHA-256. `verification.json` binds the three final
source files to the exact published-parent blobs and qualified postimages.
The two `independent-*.json` reports independently verify these source bindings,
all archive members, and the Core archive's original inner manifest.

The earlier Intel Core structured-input case failed one attempt but recovered
under the configured retry policy. Its final target result was flaky, rather
than the terminal Intel blocker. The PTY target was the terminal Intel failure.
The structured-input failure remains recorded and its cause is still under
investigation; this checkpoint does not claim to repair it.

These are component qualifications at their recorded sources. The combined
candidate must obtain its own required hosted checks, including Intel macOS,
Windows, dependency policy, and the original NextUse timing diagnostic. Main
merge and branch deletion remain subject to those checks and exact-tip ancestry.
The existing HIA exclusions and all original caller allowlists remain unchanged.
