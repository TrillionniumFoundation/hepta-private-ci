"""Conservative Python-object cache admission accounting for shadow research.

The feature and Q24 projection caches store immutable Python tuples of boxed
float/int values, NOT packed 4-byte/8-byte device tensors. Accounting only
payload width systematically underestimates their resident size. The estimate
includes each key, boxed vector elements, record metadata and a per-entry
OrderedDict/allocator margin. It is *not* independently measured RSS, and does
not cover ephemeral model activations, tokenizer tensors, CUDA or WAL.
"""

import sys

# Safety margin for OrderedDict nodes, allocator bookkeeping and changing hash
# table capacities. Deliberately count shared immutable strings once PER entry
# to fail closed rather than depend on implementation-specific interning.
ENTRY_MARGIN_BYTES = 256


def estimated_python_cache_entry_bytes(key, value, vector):
    if type(key) is not tuple or type(vector) is not tuple or not hasattr(value, "__dict__"):
        raise ValueError("unexpected cache entry representation")
    if not vector:
        raise ValueError("cannot cache empty feature vectors")
    count = ENTRY_MARGIN_BYTES + sys.getsizeof(key) + sys.getsizeof(value)
    count += sys.getsizeof(vars(value)) + sys.getsizeof(vector)
    count += sum(sys.getsizeof(item) for item in key)
    count += sum(sys.getsizeof(item) for item in vector)
    count += sum(sys.getsizeof(item) for item in vars(value).values() if isinstance(item, str))
    return count
