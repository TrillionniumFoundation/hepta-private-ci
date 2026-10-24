import codecs


class Utf8Lines:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.pending = ""
        self.closed = False

    def feed(self, chunk):
        if self.closed:
            raise ValueError("already finished")
        self.pending += self.decoder.decode(chunk, final=False)
        parts = self.pending.split("\n")
        self.pending = parts.pop()
        return [part[:-1] if part.endswith("\r") else part for part in parts]

    def finish(self):
        if self.closed:
            raise ValueError("already finished")
        self.pending += self.decoder.decode(b"", final=True)
        self.closed = True
        last = self.pending
        self.pending = ""
        return [last] if last else []
