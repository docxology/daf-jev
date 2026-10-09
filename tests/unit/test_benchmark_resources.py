import asyncio
import os

import pytest

from daf_jev.benchmark_resources import ResourceSampler, hardware_identity


def test_actual_read_only_hardware_and_process_sampling():
    psutil = pytest.importorskip("psutil")
    identity = hardware_identity()
    assert identity["machine"]
    process = psutil.Process(os.getpid())
    sampler = ResourceSampler({"pid": process.pid, "create_time": process.create_time()})
    async def collect():
        task = asyncio.create_task(sampler.monitor())
        await asyncio.sleep(.12)
        result = sampler.finish()
        await task
        return result
    result = asyncio.run(collect())
    assert result["wall_s"] > .1
    assert result["observed_peak_rss_bytes"] > 0
    assert result["local_expense_usd"] is None
    assert result["samples"] >= 2
    with pytest.raises(ValueError, match="identity"):
        ResourceSampler({"pid": process.pid, "create_time": 0})
