"""Bounded local pipe framing; caller owns descriptors and request semantics.

No reader thread, authentication, cancellation effect, or descriptor close here.
Timeout/EOF/malformed input permanently faults that FrameReader. A full frame is
returned only after strict canonical JSON validation; no partial command escapes.
"""
import json
import os
import select
import struct
import time

MAX_BYTES = 2048


class ChannelError(ValueError):
    pass


class ChannelTimeout(ChannelError):
    pass


class ChannelEOF(ChannelError):
    pass


class PartialFrameEOF(ChannelEOF):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _deadline(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ChannelError('deadline must be a nonnegative int below 2**63')
    return value


def _fd(value):
    if type(value) is not int or value < 0:
        raise ChannelError('file descriptor must be a nonnegative int')
    os.set_blocking(value, False)
    return value


def _remaining(deadline_ns):
    remaining = deadline_ns - time.monotonic_ns()
    if remaining <= 0:
        raise ChannelTimeout('control channel deadline expired')
    return remaining / 1_000_000_000


def _wait(fd, deadline_ns, writing=False):
    while True:
        timeout = _remaining(deadline_ns)
        try:
            ready = select.select([] if writing else [fd],
                                  [fd] if writing else [], [], timeout)
        except InterruptedError:
            continue
        _remaining(deadline_ns)
        if ready[1] if writing else ready[0]:
            return


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ChannelError('duplicate JSON key in control frame')
        value[key] = item
    return value


def _nonfinite(value):
    raise ChannelError('nonfinite JSON constant in control frame')


def _decode(raw):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=_nonfinite)
        if canonical(value) != raw:
            raise ChannelError('noncanonical control frame')
        return value
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as error:
        if isinstance(error, ChannelError):
            raise
        raise ChannelError('invalid control frame JSON') from error


class FrameReader:
    def __init__(self, fd):
        self.fd = _fd(fd)
        self._header = bytearray()
        self._body = bytearray()
        self._length = None
        self._failed = False

    def read(self, deadline_ns):
        """Return one canonical JSON frame or permanently fail this reader.

        Reads never extend beyond the current header/body, so another complete
        frame remains in the pipe for the next call. Buffer size <= 4 + 2048.
        """
        if self._failed:
            raise ChannelError('control reader is faulted')
        try:
            deadline_ns = _deadline(deadline_ns)
            while True:
                target = self._header if self._length is None else self._body
                needed = (4 if self._length is None else self._length) - len(target)
                if needed:
                    _wait(self.fd, deadline_ns)
                    try:
                        chunk = os.read(self.fd, needed)
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not chunk:
                        if self._header or self._body:
                            raise PartialFrameEOF('EOF inside control frame')
                        raise ChannelEOF('EOF before control frame')
                    target.extend(chunk)
                    continue
                if self._length is None:
                    self._length = struct.unpack('!I', self._header)[0]
                    if not 1 <= self._length <= MAX_BYTES:
                        raise ChannelError('control frame length outside 1..2048')
                    continue
                value = _decode(bytes(self._body))
                self._header.clear()
                self._body.clear()
                self._length = None
                return value
        except BaseException:
            self._failed = True
            raise


def send(fd, value, deadline_ns):
    """Send one bounded frame; success records write completion, not receipt.

    A failure can occur after partial write. Caller must treat it as unresolved
    delivery rather than automatically resending. Descriptors remain caller-owned.
    """
    deadline_ns = _deadline(deadline_ns)
    fd = _fd(fd)
    try:
        raw = canonical(value)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ChannelError('control message is not JSON serializable') from error
    if not 1 <= len(raw) <= MAX_BYTES:
        raise ChannelError('control frame length outside 1..2048')
    frame = struct.pack('!I', len(raw)) + raw
    started = time.monotonic_ns()
    sent = 0
    while sent < len(frame):
        _wait(fd, deadline_ns, writing=True)
        try:
            size = os.write(fd, frame[sent:])
        except (BlockingIOError, InterruptedError):
            continue
        except BrokenPipeError as error:
            raise ChannelEOF('control pipe has no reader') from error
        if size <= 0:
            raise ChannelError('control pipe write made no progress')
        sent += size
    return {'send_begin_ns': started, 'write_complete_ns': time.monotonic_ns()}
