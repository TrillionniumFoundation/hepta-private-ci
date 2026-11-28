# Reproduce the hardware observations

Use a fresh working directory on a ROCm host with Torch and NumPy. Starting inside this repository's `trimodal_device/meter` directory, copy the original sealed native program and result and reconstruct its weights:

```sh
work=$(mktemp -d)
cp ../native/task.py "$work/native.py"
cp ../native/result.json ./*.py "$work/"
mkdir "$work/tri_private_scores"
cat ../native/raw/raw.tar.gz.part-* > "$work/weights.tar.gz"
sha256sum "$work/weights.tar.gz"
tar -xzf "$work/weights.tar.gz" -C "$work/tri_private_scores"
cd "$work"
python device_meter.py
python stream_measure.py
python native_recount.py
```

The reassembled raw archive is 1,365,186 bytes and its SHA-256 is `cbaf4c7ece2111048d36c5f52d76defbeef39457a5958a39c6e381cffca8d1c6`. The setup script independently asserts the exact native program SHA and embedded-table SHA. Device measurement expects a readable amdgpu hwmon exposing `power1_average`, `power1_label` and edge temperature, and the DRM node's `gpu_busy_percent`. These describe the original physical host. The streaming adapter itself requires only Torch; CPU recount reads the original arrays without acquiring a GPU. Time comparisons require the original device class and account for other package load.
