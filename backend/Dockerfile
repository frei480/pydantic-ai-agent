FROM python:3.14-slim

# ripgrep используется как инструмент полнотекстового поиска агента.
# Пакет ставится напрямую из .deb, закоммиченного в репозиторий (packages/README.md):
# сборка образа не ходит в apt-репозитории — развёртывание в изолированной сети.
# ripgrep 14.1.1-1+b4 (Debian trixie, amd64); зависимости (libc6, libgcc-s1,
# libpcre2-8-0) уже входят в базовый образ.
# Bash агенту недоступен: никакая функция shell в приложении не реализована.
COPY packages/ripgrep_14.1.1-1+b4_amd64.deb /tmp/ripgrep.deb
RUN dpkg -i /tmp/ripgrep.deb \
    && rm -f /tmp/ripgrep.deb

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
