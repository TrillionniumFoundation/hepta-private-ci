# Restore actual hosted CI execution

The original scope, V8 metadata and blob-size jobs fetched every historical
branch and tag before inspecting two known pull-request commits. Scope reached
its unchanged five-minute deadline and skipped its dependent jobs. Commit
030670f74300e65777abc768c049b5140f9acd29 repairs that lane; its original hosted
scope subsequently passed in 29 seconds. This successor applies the same
existing exact-input helper to V8 metadata and blob-size comparison for PRs.
Non-PR history behavior, change detectors, the 512,000-byte policy, allowlist,
job deadlines and all substantive tests remain unchanged.

The existing Fence 0.10.0 step also failed before checkout on ubuntu-24.04 with
`unsupported_resolver_layout` (job126070689483, run41679961860). The complete
original log is retained. Update its exact official action pin to 0.12.7,
9d10445098284f8e8bbf67495fc8c2eaa34c28c5. Its checked-in bundle manifest binds
reviewed source 8a0652dd8357adcadb235fbef5016e14a382dbde to the 2,184,600-byte
binary with SHA-256
8ac3aaac8e4d29d148121038b2ed26714afc24ff2c7a61f15d507979419e787d. Actual local
bytes match that official release digest. The action input/runs contract is
byte-identical to the previous pin.

The official resolver implementation now accepts a root-owned regular
/etc/resolv.conf as well as the reviewed systemd layout. It still checks
canonical directories, ownership, unsafe permissions, runner writability,
read-only bind identity/content/options and live target stability. The
workflow retains Fence first and retains its original audit mode, read-only
permissions and normal failure propagation. No allowlist expansion, resolver
rewrite, protection bypass or continue-on-error is introduced.

The existing V8 detector's seven tests and exact-history helper's five tests
passed. Official actionlint 1.7.12 accepts the two changed workflows. The
previous scope repair retains its 59 original regressions and three real
shallow/full comparisons. This local evidence does not establish that the
new Fence runtime succeeds on the actual hosted image; the new original CI
run must supply that result, including its post-job checks.

This is a Draft / HOLD_NO_GO integration repair. All dependency, native,
product, scientific and performance gates retain their original criteria.
