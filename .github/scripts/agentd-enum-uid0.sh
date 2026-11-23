set -euo pipefail
arm=$1
case $arm in base|candidate) ;; *) exit 2 ;; esac
rootdir=/run/hepta-agentd-enum-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT-$arm
export HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=$rootdir/bind
export HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=$rootdir/source
export HEPTA_CHECKPOINT_TEST_ROOT=$rootdir/checkpoints
export HEPTA_Q24_FACTORY_WITNESS_BIND=$rootdir/witness-bind
export HEPTA_Q24_FACTORY_WITNESS_SOURCE=$rootdir/witness-source
sudo -n mkdir -m 700 "$rootdir"
cleanup() {
  for target in witness-bind bind; do
    if sudo -n mountpoint -q "$rootdir/$target"; then sudo -n umount "$rootdir/$target"; fi
  done
}
trap cleanup EXIT
sudo -n mkdir -m 700 "$rootdir/source" "$rootdir/bind" "$rootdir/checkpoints" "$rootdir/witness-source" "$rootdir/witness-bind"
sudo -n mount --bind "$rootdir/source" "$rootdir/bind"
sudo -n mount --bind "$rootdir/witness-source" "$rootdir/witness-bind"
python3 "$RUNNER_TEMP/enum-driver.py" native-arm "$arm"
