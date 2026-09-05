"""Issue #95 hard-timeout regressions."""
from __future__ import annotations

import operator
import time


def _timed_sleep(duration):
    started = time.monotonic()
    time.sleep(duration)
    return started, time.monotonic()


def test_process_jobs_terminate_timed_out_worker_and_return_fast():
    from lib.pipeline.process_runner import ProcessJob, run_process_jobs

    jobs = [
        ProcessJob(key="fast", target=operator.add, args=(1, 2), timeout_sec=5.0),
        ProcessJob(key="slow", target=time.sleep, args=(30.0,), timeout_sec=0.05),
    ]

    started = time.monotonic()
    outcomes = {item.key: item for item in run_process_jobs(jobs, max_workers=2, overall_timeout=8.0)}
    elapsed = time.monotonic() - started

    assert elapsed < 10.0  # Includes interpreter startup and worker cleanup on CI.
    assert outcomes["fast"].value == 3
    assert outcomes["fast"].error is None
    assert outcomes["slow"].timed_out is True
    assert "timeout" in outcomes["slow"].error


def test_process_jobs_serialize_members_of_same_group():
    from lib.pipeline.process_runner import ProcessJob, run_process_jobs

    jobs = [
        ProcessJob(key="mini-a", target=_timed_sleep, args=(0.08,), timeout_sec=5.0, serial_group="mini"),
        ProcessJob(key="mini-b", target=_timed_sleep, args=(0.08,), timeout_sec=5.0, serial_group="mini"),
        ProcessJob(key="regular", target=_timed_sleep, args=(0.08,), timeout_sec=5.0),
    ]

    started = time.monotonic()
    outcomes = run_process_jobs(jobs, max_workers=3, overall_timeout=15.0)
    elapsed = time.monotonic() - started

    assert len(outcomes) == 3
    assert all(item.error is None for item in outcomes)
    intervals = {item.key: item.value for item in outcomes}
    assert intervals["mini-b"][0] >= intervals["mini-a"][1]
    assert elapsed < 15.0
