import asyncio

from app.services.difficulty_controller import adjust_difficulty


def _run(coro):
    return asyncio.run(coro)


def test_adjust_difficulty_increase_and_cap() -> None:
    assert _run(adjust_difficulty(1, True)) == 2
    assert _run(adjust_difficulty(2, True)) == 3
    assert _run(adjust_difficulty(3, True)) == 3


def test_adjust_difficulty_decrease_and_floor() -> None:
    assert _run(adjust_difficulty(3, False)) == 2
    assert _run(adjust_difficulty(2, False)) == 1
    assert _run(adjust_difficulty(1, False)) == 1
