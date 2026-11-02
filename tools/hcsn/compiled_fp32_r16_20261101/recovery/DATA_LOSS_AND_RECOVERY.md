# Executor reset: explicit evidence loss and recovery

The original C++ working directory disappeared when the executor was reset
after the shared filesystem filled. The complete original 768-row C++ raw
validation files, raw branch observations, and 36 individual timing batches
were not uploaded before the reset and are not presently recoverable from
their summaries. They must not be described as preserved or independently
reviewable. The original Python R16 capsule, including its complete 512-row
independent validation, was safely published at repository commit
1e91c5cf18272505508b9ce880fd34879bb6a546.

The C++ source in this recovery directory was reconstructed from the complete
tool-call inputs still present in the conversation. Its fixed constants were
regenerated from the byte-verified published Python inputs. Their SHA256 is
d44d34cf51bcc70ef1961fdbef964ed2b703512f3d371683e743365c16d9ea4e,
matching the pre-reset constant header. RECOVERED_BUILD.json records the new
compiler invocation and binary identity. The previously reported binary hash
was a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615.
Original per-file source seals and the complete original protocol bytes
(including its freeze timestamp) were not separately cached, so recovery
does not inherit the old independent-validation admission.

Any run on the already opened 432/512/768 points is regression or recovery
reproduction only. A new numerical admission needs a newly sealed candidate,
protocol and independent case set. New timings belong to the new run and
cannot replace the lost original per-batch readings. Historical reported
summaries are observations, not substitutes for full raw evidence.

The claimed precision remains two-word compensated FP32. Native ordinary FP32
is not admitted, and no GPU, energy or network-training advantage is claimed.
