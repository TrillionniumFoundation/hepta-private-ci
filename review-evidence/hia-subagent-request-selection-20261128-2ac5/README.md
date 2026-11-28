# Exact child request and terminal completion

The recording matcher runs before the custom matcher in the original test support. A captured first request can therefore be a parent request which did not match the child continuation response. The previous completion barrier selected that parent, whose terminal event had already been consumed by submit_turn.

The test now polls within its original two-second request budget for the same child body condition used by the response mock. It rejects the parent thread identity and preserves the existing exact child/turn terminal barrier, ten-second event budget, two-second hook budget, and every original hook/lifecycle assertion.

The preserved unmodified case failed on macOS as well as Windows. Temporary event diagnostics observed only the child completion notification on the incorrectly selected parent stream; the diagnostic source was restored. With the exact request selection, the same original test passed once in 0.675 seconds (16.532 seconds including compilation), with no retry or flaky result. The candidate source was unchanged throughout and the peer's worktree was restored afterwards.

This is one actual macOS original-case result. The complete Windows consumers remain pending the combined marker and residency candidate. Their earlier complete failures remain preserved in their originating commits.
