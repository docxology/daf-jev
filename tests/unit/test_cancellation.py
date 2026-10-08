"""Task-boundary cancellation evidence without depending on copied attributes."""
import asyncio

import pytest

from daf_jev._cancellation import (
    cancellation_workflow,
    mark_cancellation,
    original_cancellation,
)


def test_original_cancellation_and_workflow_survive_wrappers_and_chain_cycles():
    original = asyncio.CancelledError("owned cancellation")
    mark_cancellation(original)
    record = {"status": "interrupted", "attempt_ids": ["owned-attempt"]}
    original.__dict__["dafjev_workflow"] = record
    after_error = ValueError("receipt finalization failed")
    original.__cause__ = after_error
    after_error.__context__ = original
    boundary = asyncio.CancelledError()
    boundary.__context__ = original
    timeout = asyncio.TimeoutError()
    timeout.__cause__ = boundary
    assert original_cancellation(boundary) is original
    assert original_cancellation(boundary).__cause__ is after_error
    assert cancellation_workflow(timeout) is record
    assert cancellation_workflow(ValueError("unrelated")) is None


@pytest.mark.parametrize("task_layers", [1, 3])
def test_real_nested_tasks_and_wait_for_keep_cancelled_state_and_partial_work(task_layers):
    record = {"status": "interrupted", "attempt_ids": ["already-admitted"]}

    async def run():
        entered = asyncio.Event()

        async def predict(depth):
            if depth:
                return await asyncio.create_task(predict(depth - 1))
            try:
                entered.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError as error:
                mark_cancellation(error)
                error.__dict__["dafjev_workflow"] = record
                raise

        task = asyncio.create_task(predict(task_layers))
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(asyncio.TimeoutError) as caught:
            await asyncio.wait_for(task, timeout=.01)
        assert task.cancelled()
        assert cancellation_workflow(caught.value) is record

    asyncio.run(run())


def test_current_owned_cancellation_never_inherits_handled_previous_request_work():
    previous_work = {"request_hash": "previous-request", "observed_receipts": ["previous-receipt"]}

    async def run():
        entered = asyncio.Event()
        current_errors = []
        previous = asyncio.CancelledError("previous request")
        mark_cancellation(previous)
        previous.__dict__["dafjev_workflow"] = previous_work

        async def worker():
            try:
                raise previous
            except asyncio.CancelledError:
                try:
                    entered.set()
                    await asyncio.Event().wait()
                except asyncio.CancelledError as current:
                    # The actual injected cancellation automatically has the
                    # earlier handled cancellation as its context.
                    mark_cancellation(current)
                    current_errors.append(current)
                    raise

        task = asyncio.create_task(worker())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert task.cancelled()
        current = current_errors[0]
        assert current is not previous
        assert current.__context__ is previous
        assert original_cancellation(caught.value) is current
        assert cancellation_workflow(caught.value) is None

    asyncio.run(run())


def test_unrelated_exception_nodes_cannot_supply_cancellation_work():
    previous = asyncio.CancelledError("previous request")
    mark_cancellation(previous)
    previous.__dict__["dafjev_workflow"] = {"request_hash": "previous-request"}
    unrelated = ValueError("unrelated processing")
    unrelated.__context__ = previous
    current = asyncio.CancelledError()
    current.__context__ = unrelated
    timeout = asyncio.TimeoutError()
    timeout.__cause__ = unrelated
    assert original_cancellation(current) is current
    assert cancellation_workflow(current) is None
    assert cancellation_workflow(timeout) is None
    timeout.__context__ = previous
    timeout.__cause__ = None
    assert cancellation_workflow(timeout) is None


def test_unmarked_normalization_cycle_terminates_without_evidence():
    cancellation = asyncio.CancelledError()
    timeout = asyncio.TimeoutError()
    cancellation.__context__ = timeout
    timeout.__cause__ = cancellation
    assert original_cancellation(cancellation) is cancellation
    assert cancellation_workflow(cancellation) is None
    assert cancellation_workflow(timeout) is None
