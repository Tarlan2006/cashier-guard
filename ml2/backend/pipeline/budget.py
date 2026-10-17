"""Shared cooperative deadline. The API also enforces it in a worker process."""

from dataclasses import dataclass, field
import time


class BudgetExpired(RuntimeError):
    pass


@dataclass
class RuntimeBudget:
    started: float = field(default_factory=time.perf_counter)
    adaptive_after_sec: float = 150.0
    stop_after_sec: float = 168.0
    changes: list[dict] = field(default_factory=list)
    last_interval: float = 0.5

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    @property
    def remaining(self) -> float:
        return max(0.0, self.stop_after_sec - self.elapsed)

    def check(self) -> None:
        if self.remaining <= 0:
            raise BudgetExpired("Local processing deadline reached")

    def interval(self, video_time: float, duration: float, base: float = 0.5) -> float:
        self.check()
        interval = base
        if self.elapsed >= self.adaptive_after_sec:
            interval = max(
                2.0, min(10.0, (duration - video_time) / max(1.0, self.remaining / 1.0))
            )
        if abs(interval - self.last_interval) > 0.01:
            self.changes.append(
                dict(
                    video_time_sec=video_time,
                    elapsed_sec=self.elapsed,
                    interval_sec=interval,
                )
            )
            self.last_interval = interval
        return interval
