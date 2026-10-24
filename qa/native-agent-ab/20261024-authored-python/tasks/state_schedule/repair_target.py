import heapq


class ScheduleQueue:
    def __init__(self):
        self.heap = []
        self.pending = {}

    def schedule(self, key, value, deadline):
        self.pending[key] = value
        heapq.heappush(self.heap, (deadline, key))

    def cancel(self, key):
        if key in self.pending:
            del self.pending[key]
            return True
        return False

    def pop_due(self, now):
        result = []
        while self.heap and self.heap[0][0] <= now:
            _, key = heapq.heappop(self.heap)
            if key in self.pending:
                result.append((key, self.pending.pop(key)))
        return result
