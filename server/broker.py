"""Fan-out of server events to every connected page over Server-Sent Events.

publish() is safe to call from any thread — model calls run in worker
threads and stream their progress through here.
"""
import asyncio
import json


class Broker:
    def __init__(self):
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    @property
    def listening(self) -> bool:
        """Would a publish reach an open page right now?"""
        return self._loop is not None and bool(self._clients)

    @staticmethod
    def format(kind: str, data) -> str:
        return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def publish(self, kind: str, data) -> None:
        if self._loop is None:
            return
        message = self.format(kind, data)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fanout(message)
        else:
            self._loop.call_soon_threadsafe(self._fanout, message)

    def _fanout(self, message: str) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # a stuck tab: end its stream (None) so EventSource reconnects
                # and picks up a fresh snapshot instead of a partial history
                self._clients.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
