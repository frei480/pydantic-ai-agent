"""Фоновые запуски: реестр, буфер событий, подписка, отмена."""
import asyncio
import os
import sys

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import runs  # noqa: E402


async def collect(stream):
    return [event async for event in stream]


async def check_publish_subscribe_order():
    registry = runs.RunRegistry()
    run = registry.register(7)
    run.publish({"type": "phase", "phase": "research"})
    run.publish({"type": "text", "text": "часть"})
    run.finish("done")
    events = await collect(registry.stream_events(run, 0))
    assert [e["seq"] for e in events] == [1, 2, 3], events
    assert events[-1] == {"type": "done", "seq": 3}, events
    assert events[0] == {"type": "phase", "phase": "research", "seq": 1}, events


async def check_resume_from_seq():
    registry = runs.RunRegistry()
    run = registry.register(7)
    run.publish({"type": "text", "text": "a"})
    run.publish({"type": "text", "text": "b"})
    run.finish("done")
    from1 = await collect(registry.stream_events(run, 1))
    assert [e["seq"] for e in from1] == [2, 3], from1
    from3 = await collect(registry.stream_events(run, 3))
    assert from3 == [], from3


async def check_busy_chat():
    registry = runs.RunRegistry()
    registry.register(7)
    try:
        registry.register(7)
    except runs.ChatBusyError:
        pass
    else:
        raise AssertionError("второй register в занятый чат должен поднять ChatBusyError")
    other = registry.register(8)
    assert other.chat_id == 8
    run7 = registry.get(other.id)  # промежуточная проверка get
    assert run7 is other
    done = runs.RunRegistry()
    first = done.register(7)
    first.finish("done")
    second = done.register(7)
    assert second.id != first.id


async def check_cancel_semantics():
    registry = runs.RunRegistry()
    run = registry.register(1)
    run.task = asyncio.create_task(asyncio.sleep(60))
    assert run.cancel() is True
    with_npc = registry.register(2)
    with_npc.begin_finish()
    assert with_npc.cancel() is False
    with_npc.finish("cancelled")
    assert with_npc.cancel() is False
    await asyncio.sleep(0)  # отмена доставляется, когда луп даст задаче ход
    assert run.task.cancelled() or run.task.done()


async def check_heartbeat_not_buffered():
    original = runs.HEARTBEAT_SECONDS
    runs.HEARTBEAT_SECONDS = 0.05
    try:
        registry = runs.RunRegistry()
        run = registry.register(1)
        received = []

        async def consumer():
            async for event in registry.stream_events(run, 0):
                received.append(event)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.2)
        assert any(e == {"type": "heartbeat"} for e in received), received
        run.publish({"type": "text", "text": "x"})
        run.finish("done")
        await asyncio.wait_for(task, timeout=5)
        assert len(run.events) == 2, run.events
        assert run.events[-1]["seq"] == 2, run.events
        assert received[-1] == {"type": "done", "seq": 2}, received
    finally:
        runs.HEARTBEAT_SECONDS = original


async def check_reap_old_finished():
    original = runs.TERMINAL_KEEP_SECONDS
    runs.TERMINAL_KEEP_SECONDS = 0.0
    try:
        registry = runs.RunRegistry()
        finished = registry.register(1)
        finished.publish({"type": "text", "text": "x"})
        finished.finish("done")
        alive = registry.register(2)
        registry.reap()
        assert registry.get(finished.id) is None
        assert registry.get(alive.id) is alive
    finally:
        runs.TERMINAL_KEEP_SECONDS = original


asyncio.run(check_publish_subscribe_order())
asyncio.run(check_resume_from_seq())
asyncio.run(check_busy_chat())
asyncio.run(check_cancel_semantics())
asyncio.run(check_heartbeat_not_buffered())
asyncio.run(check_reap_old_finished())
print("RUNS-REGISTRY-OK")
