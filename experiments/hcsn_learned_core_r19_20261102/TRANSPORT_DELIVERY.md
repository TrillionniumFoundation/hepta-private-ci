# Exact evidence transport

The fitted-byte bundle at `transport_preconfirm` restores all 80 actual checkpoints and training evidence. It was published at c4954a2e67a1ba12fb980472f040a3adaeb325a6 before confirmation opened.

The selected `transport_confirm_compact` bundle contains 132 base64 parts plus INDEX.json and MANIFEST.json.gz. It reconstructs all 248 original confirmation/measurement files, including 240 complete raw traces, byte for byte. The original 31,098,310 gzip/other bytes are represented by a 7,884,007-byte archive through exact FP32/FP64 binary columns and shared objects. Nothing is rounded.

Run `python compact_transport.py restore --source transport_confirm_compact --destination FRESH_DIRECTORY` with NumPy. Original gzip serialization is re-created under the recorded Python/zlib format and every original SHA256 is checked; an incompatible serializer fails verification. The decoder creates a fresh destination and never replaces existing files.

The first generic tar bundle and byte-shuffle alternative were retained locally but not selected for publication. TRANSPORT_COMPARISON.json reports actual sizes and known/unknown packaging costs. Packaging and the 23.063303 CPU-second exact restore are separate from the 158.574751 CPU seconds of scientific training/confirmation.

The original positive core-gain gate remains false.
