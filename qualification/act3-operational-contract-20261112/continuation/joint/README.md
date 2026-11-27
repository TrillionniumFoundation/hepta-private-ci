# Joint original async invocation and controller recovery

Exact code `953cb7b3dcc73182f2acf711807155b96d84475b`, tree
`4db3d939d077eb0ee93e2c03dc21388745f50357`, matches the local complete index.
Five final-source tests passed after formatting. Every retained control SQLite
source hash matches the frozen source postimages. The owning formatter/check
then made no further changes.

The bridge commits MAY_HAVE_DISPATCHED before child creation and
release_attempted before its one release send. A restored controller only reads
the exact original effect and cannot start or release a worker. It preserves
the original boot, source, spec, deadline, pause and observation budget.
Pause only fences release: an already released autonomous invocation cannot be
paused through this API, and a request to do so is rejected.

The actual after-release cut holds the original worker with its retained pidfd.
The original controller persists/sends release and exits. A distinct controller
restores, observes UNKNOWN and is refused a new release. Only then does the test
supervisor continue the same worker through the original pidfd. Actual canonical
intent/value bytes establish completion. A subsequent foreign intent is refused;
both intent versions and the restored original are retained.

The other cases cover death before release without replay, preserved exhausted
observation budget and writer/parameter binding, pause/deadline expiry without
release, and a caller changing its goal during admission. The latter validates
the repaired parameter-freezing gap: the worker now receives only the immutable
spec copy already persisted by the controller.

`joint-final-originals.tar.xz` retains all five raw fixture directories, original
SQLite and payload bytes, controller/worker events, final source postimages and
test log. The independent audit checks the actual causal sequence and original
versus rejected bytes. The hosted workflow now invokes the same CLI with raw
evidence retention. Hosted exact-source execution remains independent.

This closes only the Linux, same-UID, same-boot, single-invocation fixture gate.
It does not establish policy/GRU hidden-state recovery, general asynchronous
taskflow recovery, hostile-writer protection, power-loss/common-rollback safety,
production Root/AuthBus/FinalUse, application generalization or learning gain.
The old v8 success is retained separately as metadata success with two build jobs
skipped, not native execution qualification. All remaining gates stay explicit
in the parent `BLOCKERS.json`; adoption remains false.
