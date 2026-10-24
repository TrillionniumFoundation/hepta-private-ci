class ByteFramer:
    def __init__(self, max_payload=1024):
        if type(max_payload) is not int or not 0 <= max_payload <= 65535:
            raise ValueError("invalid maximum")
        self.max_payload = max_payload
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        result = []
        while len(self.buffer) >= 2:
            size = int.from_bytes(self.buffer[:2], "big")
            if size > self.max_payload:
                raise ValueError("frame too large")
            del self.buffer[:2]
            if len(self.buffer) < size:
                break
            if size:
                result.append(bytes(self.buffer[:size]))
            del self.buffer[:size]
        return result

    def finish(self):
        if self.buffer:
            raise ValueError("truncated frame")
