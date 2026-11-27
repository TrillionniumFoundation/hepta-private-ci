# Original 33f artifact custody

The four artifacts exposed by GitHub for run 46071556745 are retained exactly in ordered SHA-256 chunks. Reconstruct each ZIP by concatenating the index entries in order; the original ZIP size, SHA-256, every member identity, and CRC are retained.

The original native-components job was cancelled after its original one-hour timeout. The published logs lack its final execution tail and its upload step has no successful terminal result. These artifacts do not change that failure or qualify the later parallel workflow. The failed direct download and successful transport are separate retained attempts.
