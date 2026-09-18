import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowCounter:
    """Fenêtre glissante en mémoire du processus.

    Correct tant qu'il n'y a qu'une instance, ce qui est le cas sur
    l'hébergement gratuit. Passer à plusieurs instances rendrait ce
    compteur inopérant : il faudrait le déplacer en base.
    """

    def __init__(self, maximum: int, window_seconds: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.maximum = maximum
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.maximum:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
