import heapq


class ScheduleQueue:
    def __init__(self):
        self.heap = []
        self.pending = {}
        self.order = 0

    def schedule(self, key, value, deadline):
        self.order += 1
        event = (deadline, self.order, value)
        self.pending[key] = event
        heapq.heappush(self.heap, (deadline, self.order, key))

    def cancel(self, key):
        if key in self.pending:
            del self.pending[key]
            return True
        return False

    def pop_due(self, now):
        result = []
        while self.heap and self.heap[0][0] <= now:
            deadline, order, key = heapq.heappop(self.heap)
            current = self.pending.get(key)
            if current is not None and current[:2] == (deadline, order):
                del self.pending[key]
                result.append((key, current[2]))
        return result
