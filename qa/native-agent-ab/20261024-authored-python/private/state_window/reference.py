from collections import deque


class WindowLimiter:
    def __init__(self, capacity, window):
        if type(capacity) is not int or capacity <= 0 or type(window) is not int or window <= 0:
            raise ValueError("invalid limits")
        self.capacity = capacity
        self.window = window
        self.events = {}
        self.last_now = None

    def allow(self, key, now):
        if self.last_now is not None and now < self.last_now:
            raise ValueError("time decreased")
        self.last_now = now
        queue = self.events.setdefault(key, deque())
        while queue and queue[0] <= now - self.window:
            queue.popleft()
        if len(queue) >= self.capacity:
            return False
        queue.append(now)
        return True
