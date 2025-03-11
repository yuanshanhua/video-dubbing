import asyncio
import concurrent.futures
import threading
import time
from concurrent.futures import Future
from typing import Coroutine, Optional, Set


class AsyncBackgroundExecutor:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop
        self._thread: threading.Thread
        self._start_event = threading.Event()
        self._pending_futures: Set[Future] = set()
        self._lock = threading.Lock()

        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="AsyncBackgroundThread")
        self._thread.start()
        self._start_event.wait()

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._start_event.set()
        self._loop.run_forever()

    def execute(self, coro: Coroutine) -> Future:
        """提交任务并跟踪Future对象"""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        with self._lock:
            self._pending_futures.add(future)
        future.add_done_callback(self._remove_future)
        return future

    def _remove_future(self, future):
        """自动移除已完成的任务"""
        with self._lock:
            self._pending_futures.discard(future)

    def wait_all(self, timeout: Optional[float] = None):
        """等待所有未完成任务执行完毕"""
        with self._lock:
            current_futures = list(self._pending_futures)

        # 使用concurrent.futures等待机制
        done, not_done = concurrent.futures.wait(
            current_futures,
            timeout=timeout,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

        if not_done:
            raise TimeoutError(f"{len(not_done)} tasks not completed within timeout")
        res = [f.result() for f in done]
        self._shutdown()
        return res

    def _shutdown(self):
        """安全关闭"""
        self._loop.call_soon_threadsafe(self._loop.stop)
        while self._loop.is_running():
            threading.Event().wait(0.1)
        self._loop.close()


if __name__ == "__main__":
    # 使用示例
    async def demo_task(n: int):
        print(f"[{threading.current_thread().name}] Task {n} started")
        await asyncio.sleep(3)
        if n == 1:
            raise ValueError("test")
        print(f"[{threading.current_thread().name}] Task {n} completed")
        return n * 10

    async def test():
        ex = AsyncBackgroundExecutor()
        st = time.time()
        for i in range(3):
            print(f"main task {i} started")
            time.sleep(3)
            print(f"main task {i} completed")
            t = demo_task(i)
            ex.execute(t)
        try:
            ex.wait_all()
        except Exception as e:
            print(e)
        print(f"All tasks completed in {time.time() - st:.2f}s")

    asyncio.run(test())
