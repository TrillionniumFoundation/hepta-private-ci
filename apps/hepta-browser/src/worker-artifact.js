const READ_CHUNK_BYTES = 16_384;

// Metadata is only an early admission check: the same open file can grow
// before or during reading. Never retain more than the admitted byte limit.
export async function readBoundedWorkerArtifact(handle, maximum) {
  if (
    !Number.isSafeInteger(maximum) ||
    maximum < 1 ||
    !Number.isSafeInteger(maximum + 1)
  ) {
    throw new TypeError("browser worker artifact byte limit is invalid");
  }
  const buffer = Buffer.alloc(Math.min(READ_CHUNK_BYTES, maximum + 1));
  const chunks = [];
  let total = 0;
  while (true) {
    const length = Math.min(buffer.length, maximum - total + 1);
    const { bytesRead } = await handle.read(buffer, 0, length, null);
    if (bytesRead === 0) break;
    if (bytesRead > maximum - total) {
      throw new TypeError(
        "browser worker artifact exceeds byte limit during read",
      );
    }
    total += bytesRead;
    chunks.push(Buffer.from(buffer.subarray(0, bytesRead)));
  }
  if (total === 0) throw new TypeError("browser worker artifact is empty");
  return Buffer.concat(chunks, total);
}
