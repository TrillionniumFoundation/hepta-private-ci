def normalize(intervals):
    pairs = []
    for start, end in intervals:
        if start > end:
            raise ValueError("reversed interval")
        if start != end:
            pairs.append((start, end))
    pairs.sort()
    result = []
    for start, end in pairs:
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result
