function inflateRawDeflate(compressed, expectedLength) {
  "use strict";
  const fail = (message) => {
    throw new Error("raw DEFLATE: " + message);
  };
  if (!Number.isSafeInteger(expectedLength) || expectedLength < 0) {
    fail("expected output length must be a nonnegative safe integer");
  }
  let input;
  if (compressed instanceof Uint8Array) {
    input = compressed;
  } else if (Array.isArray(compressed)) {
    for (let i = 0; i < compressed.length; i++) {
      if (!Number.isInteger(compressed[i]) || compressed[i] < 0 || compressed[i] > 255) {
        fail("input contains a non-byte value");
      }
    }
    input = new Uint8Array(compressed);
  } else {
    fail("input must be Uint8Array or an array of bytes");
  }
  const output = new Uint8Array(expectedLength);
  let inputPosition = 0;
  let outputPosition = 0;
  let hold = 0;
  let heldBits = 0;
  function bits(n) {
    while (heldBits < n) {
      if (inputPosition >= input.length) fail("truncated input");
      hold |= input[inputPosition++] << heldBits;
      heldBits += 8;
    }
    const result = hold & ((1 << n) - 1);
    hold >>>= n;
    heldBits -= n;
    return result;
  }
  function tree(lengths, limit, kind) {
    const counts = new Uint16Array(limit + 1);
    let maximum = 0;
    let used = 0;
    for (let symbol = 0; symbol < lengths.length; symbol++) {
      const n = lengths[symbol];
      if (!Number.isInteger(n) || n < 0 || n > limit) fail("invalid code length");
      if (n !== 0) {
        counts[n]++;
        used++;
        if (n > maximum) maximum = n;
      }
    }
    if (used === 0) {
      if (kind === "distance") return { maximum: 0 };
      fail("empty Huffman tree");
    }
    let left = 1;
    for (let n = 1; n <= limit; n++) {
      left = left * 2 - counts[n];
      if (left < 0) fail("oversubscribed Huffman tree");
    }
    if (left !== 0 && (kind === "code-length" || maximum !== 1)) {
      fail("incomplete Huffman tree");
    }
    const first = new Int32Array(limit + 1);
    const offsets = new Uint16Array(limit + 1);
    let code = 0;
    let offset = 0;
    for (let n = 1; n <= limit; n++) {
      code = (code + counts[n - 1]) * 2;
      first[n] = code;
      offsets[n] = offset;
      offset += counts[n];
    }
    const cursor = new Uint16Array(offsets);
    const symbols = new Uint16Array(used);
    for (let symbol = 0; symbol < lengths.length; symbol++) {
      const n = lengths[symbol];
      if (n !== 0) symbols[cursor[n]++] = symbol;
    }
    return { maximum, counts, first, offsets, symbols };
  }
  function symbol(t) {
    if (t.maximum === 0) fail("distance used with an empty tree");
    let code = 0;
    for (let n = 1; n <= t.maximum; n++) {
      // Code bits arrive most-significant first, even though byte packing is LSB-first.
      code = code * 2 + bits(1);
      const index = code - t.first[n];
      if (index >= 0 && index < t.counts[n]) {
        return t.symbols[t.offsets[n] + index];
      }
    }
    fail("invalid Huffman code");
  }
  const lengthBase = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27,
    31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258
  ];
  const lengthExtra = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
    2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0
  ];
  const distanceBase = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129,
    193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097,
    6145, 8193, 12289, 16385, 24577
  ];
  const distanceExtra = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6,
    6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13
  ];
  const codeLengthOrder = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
  let fixedLiteral = null;
  let fixedDistance = null;
  let finalBlock;
  do {
    finalBlock = bits(1);
    const type = bits(2);
    if (type === 0) {
      bits(heldBits & 7);
      const length = bits(16);
      const complement = bits(16);
      if ((length ^ 65535) !== complement) fail("stored block length complement mismatch");
      if (length > input.length - inputPosition) fail("truncated stored block");
      if (length > expectedLength - outputPosition) fail("output exceeds expected length");
      output.set(input.subarray(inputPosition, inputPosition + length), outputPosition);
      inputPosition += length;
      outputPosition += length;
      continue;
    }
    if (type === 3) fail("reserved block type");
    let literal;
    let distance;
    if (type === 1) {
      if (fixedLiteral === null) {
        const lengths = new Uint8Array(288);
        for (let i = 0; i < 288; i++) {
          lengths[i] = i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8;
        }
        fixedLiteral = tree(lengths, 15, "literal");
        fixedDistance = tree(new Uint8Array(32).fill(5), 15, "distance");
      }
      literal = fixedLiteral;
      distance = fixedDistance;
    } else {
      const literalCount = bits(5) + 257;
      const distanceCount = bits(5) + 1;
      const codeLengthCount = bits(4) + 4;
      if (literalCount > 286) fail("reserved literal/length alphabet size");
      const codeLengths = new Uint8Array(19);
      for (let i = 0; i < codeLengthCount; i++) codeLengths[codeLengthOrder[i]] = bits(3);
      const codeTree = tree(codeLengths, 7, "code-length");
      const lengths = new Uint8Array(literalCount + distanceCount);
      let i = 0;
      while (i < lengths.length) {
        const n = symbol(codeTree);
        if (n < 16) {
          lengths[i++] = n;
        } else {
          let count;
          let repeated;
          if (n === 16) {
            if (i === 0) fail("repeat code has no predecessor");
            count = bits(2) + 3;
            repeated = lengths[i - 1];
          } else if (n === 17) {
            count = bits(3) + 3;
            repeated = 0;
          } else if (n === 18) {
            count = bits(7) + 11;
            repeated = 0;
          } else {
            fail("invalid code-length symbol");
          }
          if (count > lengths.length - i) fail("code-length repeat exceeds alphabet");
          lengths.fill(repeated, i, i + count);
          i += count;
        }
      }
      if (lengths[256] === 0) fail("missing end-of-block code");
      literal = tree(lengths.subarray(0, literalCount), 15, "literal");
      distance = tree(lengths.subarray(literalCount), 15, "distance");
    }
    for (;;) {
      const value = symbol(literal);
      if (value < 256) {
        if (outputPosition >= expectedLength) fail("output exceeds expected length");
        output[outputPosition++] = value;
      } else if (value === 256) {
        break;
      } else {
        if (value > 285) fail("reserved length symbol");
        const li = value - 257;
        const length = lengthBase[li] + bits(lengthExtra[li]);
        const di = symbol(distance);
        if (di > 29) fail("reserved distance symbol");
        const back = distanceBase[di] + bits(distanceExtra[di]);
        if (back > outputPosition) fail("distance precedes output history");
        if (length > expectedLength - outputPosition) fail("output exceeds expected length");
        // Forward copying intentionally permits overlapping LZ77 references.
        for (let i = 0; i < length; i++) {
          output[outputPosition] = output[outputPosition - back];
          outputPosition++;
        }
      }
    }
  } while (finalBlock === 0);
  if (outputPosition !== expectedLength) fail("output length differs from expected length");
  // Only unused padding bits in the last byte are allowed, not trailing bytes.
  if (inputPosition !== input.length) fail("trailing bytes after final block");
  return output;
}