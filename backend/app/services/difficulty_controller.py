async def adjust_difficulty(current: int, is_correct: bool) -> int:
    if is_correct:
        return min(3, current + 1)
    return max(1, current - 1)


async def difficulty_label(level: int) -> str:
    mapping = {1: "easy", 2: "medium", 3: "hard"}
    return mapping.get(level, "easy")
