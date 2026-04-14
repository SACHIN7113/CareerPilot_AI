from functools import partial
from typing import Any, Callable, TypeVar

from starlette.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    bound = partial(func, *args, **kwargs)
    return await run_in_threadpool(bound)
