class Utf8Lines:
    def __init__(self):
        self.pending = ""

    def feed(self, chunk):
        self.pending += chunk.decode("utf-8")
        parts = self.pending.split("\n")
        self.pending = parts.pop()
        return [part.strip() for part in parts]

    def finish(self):
        last = self.pending.strip()
        self.pending = ""
        return [last] if last else []
