#!/usr/bin/env sh
set -eu

# Exercise the absolute executable used by the Unix production verifier, as the
# image's non-root default user, without external network access.
test "$(id -u)" = 1000
test -x /usr/bin/ssh-keygen
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT HUP INT TERM

/usr/bin/ssh-keygen -q -t ed25519 -N '' -f "$smoke_dir/key"
printf 'hepta-bazel-smoke %s\n' "$(cat "$smoke_dir/key.pub")" > "$smoke_dir/allowed_signers"
printf 'hepta operator fixture payload\n' > "$smoke_dir/payload"
/usr/bin/ssh-keygen -Y sign -f "$smoke_dir/key" -n hepta-bazel-smoke "$smoke_dir/payload"
/usr/bin/ssh-keygen -Y verify \
  -f "$smoke_dir/allowed_signers" -I hepta-bazel-smoke \
  -n hepta-bazel-smoke -s "$smoke_dir/payload.sig" < "$smoke_dir/payload"

printf 'altered operator fixture payload\n' > "$smoke_dir/altered"
if /usr/bin/ssh-keygen -Y verify \
  -f "$smoke_dir/allowed_signers" -I hepta-bazel-smoke \
  -n hepta-bazel-smoke -s "$smoke_dir/payload.sig" < "$smoke_dir/altered"; then
  echo 'ERROR: altered payload was accepted' >&2
  exit 1
fi
if /usr/bin/ssh-keygen -Y verify \
  -f "$smoke_dir/allowed_signers" -I hepta-bazel-smoke \
  -n wrong-namespace -s "$smoke_dir/payload.sig" < "$smoke_dir/payload"; then
  echo 'ERROR: wrong signing namespace was accepted' >&2
  exit 1
fi
printf '%s\n' 'PASS: default UID 1000; signature accepted; altered payload and wrong namespace rejected'
