"""Реестр фоновых запусков агента — в памяти одного процесса бэкенда.

Запуск живёт независимо от HTTP-соединений: события пайплайна копятся
в буфер с порядковыми номерами, подписчики читают их догоняющим потоком
(сначала накопленные после ``from_seq``, потом новые вживую). Реестр
атомарен без блокировок: публикация и регистрация подписчика — обычные
синхронные методы на однопоточном event loop.
"""
import asyncio
import time
import uuid

from typing import AsyncIterator

# Завершающие события потока: после них подписка закрывается.
TERMINAL_TYPES = frozenset({"done", "error", "cancelled"})
# Пока событий нет, подписчику шлется heartbeat — nginx не закрывает
# соединение (proxy_read_timeout 600s).
HEARTBEAT_SECONDS = 15.0
# Сколько завершённый запуск остаётся в реестре — на случай обрыва связи
# в момент завершения; ответ к этому времени уже в базе.
TERMINAL_KEEP_SECONDS = 60.0
# Сколько ждать останова запуска при удалении чата.
STOP_WAIT_SECONDS = 5.0


class ChatBusyError(RuntimeError):
    """В чате уже идёт запуск — второй одновременный запрещён."""


class Run:
    """Один запуск пайплайна: буфер событий, статус, фоновая задача."""

    def __init__(self, run_id: str, chat_id: int) -> None:
        self.id = run_id
        self.chat_id = chat_id
        self.status = "running"  # running | done | error | cancelled
        self.events: list[dict] = []
        self.task: asyncio.Task | None = None
        # Окно записи ответа: агент закончил, ответ сохраняется —
        # отмена больше не действует, запуск считается завершающимся.
        self.finishing = False
        self.finished_at: float | None = None
        self._queues: list[asyncio.Queue] = []

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def publish(self, event: dict) -> None:
        """Событие в буфер (с seq) и всем подписчикам."""
        stored = {**event, "seq": len(self.events) + 1}
        self.events.append(stored)
        for queue in self._queues:
            queue.put_nowait(stored)

    def begin_finish(self) -> None:
        """Войти в окно записи ответа: отмена не действует."""
        self.finishing = True

    def finish(self, status: str, **fields) -> None:
        """Завершить запуск и опубликовать завершающее событие."""
        self.status = status
        self.finished_at = time.monotonic()
        self.publish({"type": status, **fields})

    def cancel(self) -> bool:
        """Отменить запуск; False — уже завершён или в окне записи."""
        if self.status != "running" or self.finishing:
            return False
        if self.task is not None:
            self.task.cancel()
        return True

    def bind_task(self, task: asyncio.Task) -> None:
        """Привязать фоновую задачу; страховка от вечного running.

        Если задача завершилась, а терминальный статус не поставлен
        (сбой самого обработчика, отмена не стартовавшей задачи),
        запуск закрывается ошибкой — чат не остаётся «занятым».
        """
        self.task = task
        task.add_done_callback(self._finish_if_running)

    def _finish_if_running(self, task: asyncio.Task) -> None:
        if self.status == "running":
            self.finish("error", message="Запуск завершился без статуса")


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def register(self, chat_id: int) -> Run:
        """Зарегистрировать запуск; синхронно — занятость чата атомарна."""
        if self.active_run_id(chat_id) is not None:
            raise ChatBusyError(f"chat {chat_id} already has a running run")
        run = Run(str(uuid.uuid4()), chat_id)
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def discard(self, run: Run) -> None:
        """Убрать запуск, не начавшийся (сбой до старта задачи).

        Задачи у такого запуска нет — cancel() его не завершит, а чат
        он держит занятым. Вызывается при сбое сохранения вопроса.
        """
        self._runs.pop(run.id, None)

    def active_run_id(self, chat_id: int) -> str | None:
        for run in self._runs.values():
            if run.chat_id == chat_id and run.is_running:
                return run.id
        return None

    def active_run(self, chat_id: int) -> Run | None:
        run_id = self.active_run_id(chat_id)
        return self._runs.get(run_id) if run_id else None

    def reap(self) -> None:
        """Удалить завершённые запуски старее TERMINAL_KEEP_SECONDS."""
        now = time.monotonic()
        stale = [
            run_id
            for run_id, run in self._runs.items()
            if run.finished_at is not None
            and now - run.finished_at > TERMINAL_KEEP_SECONDS
        ]
        for run_id in stale:
            del self._runs[run_id]

    async def stop_chat_run(self, chat_id: int) -> None:
        """Отменить активный запуск чата и дождаться его конца (до 5 с)."""
        run = self.active_run(chat_id)
        if run is None:
            return
        run.cancel()
        if run.task is not None:
            # asyncio.wait не отменяет задачу по таймауту — просто перестаём ждать.
            await asyncio.wait({run.task}, timeout=STOP_WAIT_SECONDS)

    def cancel_all(self) -> list[Run]:
        """Отменить все активные запуски (остановка сервера)."""
        cancelled = [
            run for run in self._runs.values() if run.is_running and run.cancel()
        ]
        return cancelled

    async def stream_events(
        self, run: Run, from_seq: int = 0
    ) -> AsyncIterator[dict]:
        """События запуска после from_seq: накопленные, потом новые вживую.

        Регистрация очереди ДО снимка буфера (без await между ними) —
        событие, вышедшее во время реплея, не теряется и не дублируется.
        Heartbeat — только подписчику, в буфер не попадает. Поток
        заканчивается после завершающего события.
        """
        queue: asyncio.Queue = asyncio.Queue()
        run._queues.append(queue)
        try:
            snapshot = list(run.events)
            for event in snapshot:
                if event["seq"] > from_seq:
                    yield event
                    if event["type"] in TERMINAL_TYPES:
                        return
            if run.status != "running":
                last = run.events[-1] if run.events else None
                if last is None or last["seq"] <= from_seq:
                    return  # завершающее событие уже у клиента
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat"}
                    continue
                yield event
                if event["type"] in TERMINAL_TYPES:
                    return
        finally:
            try:
                run._queues.remove(queue)
            except ValueError:
                pass
