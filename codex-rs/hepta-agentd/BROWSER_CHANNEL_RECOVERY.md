# Native Browser channel recovery

`BrowserServoPort` remains the Agentd-side owner of the private ordered service
channel. It uses the existing `FinalUseAuthority` and the existing Browser
operation journal. No new effect executor, journal, grant issuer or retry owner
is introduced.

## Exchange fence

Complete local encoding must succeed before an outgoing sequence is spent.
Starting a transport write then fences the exchange: a failed write can have
exposed a prefix, and a timed-out read can still receive a late response. A
malformed frame, wrong request/sequence, failed authority challenge or incomplete
dispatch boundary does not reset this fence. Later calls on the same port return
`Indeterminate` without further reads, writes or final-use claims.

Only a complete matching response envelope settles transport. A service rejection
can settle the exchange, but neither a rejection nor an `ok` envelope proves
external task terminality. In particular, an indeterminate Browser operation can
be returned inside a successfully delivered response and remains indeterminate.

The existing operation owner must preserve and reconcile its original operation
identity and journal. A failed channel has no reset/retry method. Replacing a
channel or process is not permission to redispatch, issue a fresh operation ID,
replace the journal, release an unresolved resource reservation or forget a
consumed authority nonce. Recovery uses a fresh admitted service channel only
under the existing generation, artifact, profile and journal-owner rules.

## Bounded-reader shutdown

The child transport disconnects its receiver before killing/reaping the child
and joining its reader. A bounded `sync_channel(1)` reader can otherwise be
blocked sending its second frame while the destructor waits forever for that
same reader. Killing the child does not unblock a thread blocked in `send`.

This change addresses that specific queue/join deadlock. It does not establish
hostile-descendant containment, interruptible pipe writes, durable cross-process
cleanup, complete process-tree death, device-memory release or an independent
terminal observation. Those remain obligations of the existing supervised host.

## Regression and evidence scope

The existing source-head/base-merge Browser composition workflow selects the
new `browser_servo::recovery_tests` through its `browser_servo` filter:

```sh
cd codex-rs
just test --locked --lib -p codex-hepta-agentd --retries 0 --test-threads=1 browser_servo
```

Eight added tests cover complete responses, explicit service rejection, envelope
size rejection after a valid payload, partial writes, late responses after a
read failure, malformed/incorrect replies, safe-integer sequence exhaustion and
real-child cleanup with a full bounded reader queue. Most transport observations
are controlled fixtures. The cleanup case launches a real POSIX child; it is not
a real Servo task. Existing cryptographic final-use tests remain unchanged.

The editing environment ran the full Browser JavaScript suite (156 passed) and
scoped `test_hepta*.py` suite (104 passed) on the unchanged JS/Python source bytes.
It had no Rust/Cargo/just toolchain: `just fmt` exited 127. These scoped passes do
not validate this Rust change. Actual native formatting, compilation, tests,
strict lint and complete candidate qualification must be read for the exact
current source and fixed-base merge; queued, historical and skipped results are
not substituted. In particular the predecessor's Agentd lint failures outside
`DecodedFrame.sequence` have not been repaired by this channel change.
