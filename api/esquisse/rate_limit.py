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
        self._passages: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, cle: str) -> bool:
        maintenant = self.clock()
        passages = self._passages[cle]
        while passages and maintenant - passages[0] > self.window:
            passages.popleft()
        if len(passages) >= self.maximum:
            return False
        passages.append(maintenant)
        return True

    def reset(self) -> None:
        self._passages.clear()
