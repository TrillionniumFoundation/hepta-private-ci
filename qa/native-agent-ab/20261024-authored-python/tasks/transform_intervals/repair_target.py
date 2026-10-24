def normalize(intervals):
    intervals.sort()
    result = []
    for start, end in intervals:
        if start > end:
            raise ValueError("reversed interval")
        if start == end:
            continue
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], end)
        else:
            result.append((start, end))
    return result
