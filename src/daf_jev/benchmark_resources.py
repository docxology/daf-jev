"""Read-only hardware identity and sampled process memory, no model control."""
from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import subprocess
import time
from typing import Any


def hardware_identity() -> dict[str, Any]:
    result: dict[str, Any] = {"machine": platform.machine(), "os_release": platform.release()}
    if platform.system() == "Darwin":
        for field, name in (("cpu", "machdep.cpu.brand_string"), ("physical_memory_bytes", "hw.memsize"), ("model", "hw.model")):
            value = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, check=True).stdout.strip()
            result[field] = int(value) if field == "physical_memory_bytes" else value
    else:
        result["cpu"] = platform.processor()
    return result


class ResourceSampler:
    """Observe runner+descendant RSS and explicitly identified serving process.

    Sampling is not an allocator guarantee; Metal unified-memory allocations
    may exceed RSS. No monetary rate is assumed. Invalid/reused PIDs fail before
    sampling, and no process is launched, interrupted or signaled.
    """
    def __init__(self, process: dict[str, Any] | None = None) -> None:
        import psutil
        self.psutil = psutil
        self.roots = [psutil.Process(os.getpid())]
        if process:
            server = psutil.Process(process["pid"])
            if server.create_time() != process["create_time"]:
                raise ValueError("serving process identity changed")
            self.roots.append(server)
        self.peak = 0
        self.samples = 0
        self.began = time.perf_counter()
        self.done = asyncio.Event()

    def sample(self) -> None:
        processes = {}
        for root in self.roots:
            if not root.is_running():
                continue
            processes[root.pid] = root
            for child in root.children(recursive=True):
                processes[child.pid] = child
        resident = 0
        for process in processes.values():
            try:
                resident += process.memory_info().rss
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                continue
        self.peak = max(self.peak, resident)
        self.samples += 1

    async def monitor(self) -> None:
        while not self.done.is_set():
            self.sample()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.done.wait(), timeout=.1)

    def finish(self) -> dict[str, Any]:
        self.done.set()
        self.sample()
        return {"wall_s": time.perf_counter() - self.began,
                "observed_peak_rss_bytes": self.peak, "samples": self.samples,
                "sampling_interval_s": .1, "root_pids": [p.pid for p in self.roots],
                "local_expense_usd": None,
                "memory_semantics": "sampled aggregate RSS; includes runner overhead; Metal allocations may exceed RSS"}
