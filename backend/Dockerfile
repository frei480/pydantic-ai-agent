# syntax=docker/dockerfile:1
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

# Runtime-библиотеки MIT Kerberos для доменного входа (python-gssapi/pyspnego).
# Тоже из вендоренных .deb (packages/README.md): krb5 1.21.3-5+deb13u1
# (Debian trixie, amd64), e2fsprogs/libkeyutils — их версии в таблице.
COPY packages/libgssapi-krb5-2_1.21.3-5+deb13u1_amd64.deb /tmp/krb/
COPY packages/libkrb5-3_1.21.3-5+deb13u1_amd64.deb /tmp/krb/
COPY packages/libk5crypto3_1.21.3-5+deb13u1_amd64.deb /tmp/krb/
COPY packages/libkrb5support0_1.21.3-5+deb13u1_amd64.deb /tmp/krb/
COPY packages/libcom-err2_1.47.2-3+b12_amd64.deb /tmp/krb/
COPY packages/libkeyutils1_1.6.3-6_amd64.deb /tmp/krb/
RUN dpkg -i /tmp/krb/*.deb \
    && rm -rf /tmp/krb

WORKDIR /app

COPY requirements.txt /app/requirements.txt
# Зависимости ставятся ТОЛЬКО из вендоренных wheels (backend/wheels) — без
# доступа в PyPI: развёртывание в изолированной сети. Набор wheels и есть
# фиксация версий; как обновлять — wheels/README.md. BuildKit bind-mount:
# папка wheels не попадает в слои образа. gssapi — вручную собранное колесо
# (в requirements.txt его нет, см. wheels/README.md).
RUN --mount=type=bind,source=wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links=/wheels \
    -r /app/requirements.txt gssapi

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
