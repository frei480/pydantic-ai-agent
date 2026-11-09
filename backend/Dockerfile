FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*
# ripgrep используется как инструмент полнотекстового поиска агента.
# Bash агенту недоступен: никакая функция shell в приложении не реализована.

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

# Непривилегированный пользователь: даже при баге в приложении запись возможна
# только в /app/data (SQLite). Документация монтируется ro поверх /app/docs.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

ENV DOCS_ROOT=/app/docs \
    DB_PATH=/app/data/chats.db \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
