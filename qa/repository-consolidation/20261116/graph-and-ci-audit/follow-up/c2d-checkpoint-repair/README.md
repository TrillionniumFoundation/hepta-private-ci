# Checkpoint repair evidence

This package preserves the original logs, input manifests, source proposal,
counterexamples and final native results for the first layer of the c2d source
union. The old production implementation ran the six unchanged new tests:
four failed and two passed. The final reviewed source passed all 357 tests in
three complete packages, with all 13,679 inputs unchanged through every gate.

Each numbered carrier is a complete gzip stream. Decompress the carriers in
order, concatenate their output, and verify the archive digest in the carrier
manifest. Extract the content objects and restore the original paths from the
originals manifest. Every original byte was restored and checked before this
package was created.

The result covers the recorded Linux source and runtime. The known Windows
writer path identity finding remains open. This evidence does not qualify
Windows durability, path races, production activation or the full branch
history. The earlier 50-source evidence and its failures remain separate.
