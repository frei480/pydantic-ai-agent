# Вендоренные wheels (офлайн-сборка образа)

Python-зависимости из `backend/requirements.txt` устанавливаются в
`backend/Dockerfile` только из этой папки (`pip install --no-index
--find-links=/wheels`): сборка образа не ходит в PyPI — развёртывание
в изолированной сети.

## Свойства набора

- Скачан 2026-11-19 командой `pip download -r requirements.txt` **внутри
  контейнера `python:3.14-slim`** — платформенная часть ровно под целевой
  образ: CPython 3.14, linux/amd64 (manylinux). Всего 43 wheels,
  sdist-пакетов нет — собирать ничего не нужно.
- Версии: набор wheels и есть фиксация версий (в requirements.txt указаны
  диапазоны `>=`; резолвер выбирает из того, что лежит здесь).
- **Не для Windows-разработки**: бинарные wheels (pydantic-core, uvloop,
  tiktoken, regex, pyyaml и др.) не встанут на Windows — локальная
  разработка продолжает ставить пакеты обычным `pip install -r requirements.txt`.

## Колесо gssapi (собирается вручную)

`python-gssapi` — C-extension, готовых колёс на PyPI нет. Колесо
(`gssapi-*-cp311-abi3-linux_x86_64.whl`) собирается один раз на машине
с интернетом в том же базовом образе и коммитится сюда:

```bash
docker run --rm -v "$(pwd)/backend/wheels:/out" python:3.14-slim \
  sh -c "apt-get update -qq && apt-get install -y --no-install-recommends \
  gcc libkrb5-dev && pip wheel --no-deps gssapi -w /out"
```

**Пересборка обязательна при смене базового образа** (`FROM` в Dockerfile):
колесо привязано к платформе (linux/amd64) и ABI CPython. gssapi не входит
в `requirements.txt` — Dockerfile ставит его отдельным аргументом из
`/wheels`, чтобы «pip download» набора не пытался тянуть его sdist.

## Как обновлять

1. Обновить `requirements.txt` при необходимости.
2. Перекачать набор (внутри контейнера — чтобы совпала платформа):

   ```bash
   docker run --rm \
     -v "$(pwd)/backend/wheels:/out" \
     -v "$(pwd)/backend/requirements.txt:/req/requirements.txt:ro" \
     python:3.14-slim \
     sh -c "rm -f /out/*.whl && pip download -r /req/requirements.txt -d /out"
   ```

   Перекачка стирает колесо gssapi из шага выше — пересобрать его той же
   командой и закоммитить вместе с набором.

3. Пересобрать образ (`docker compose build backend`) и прогнать чеки.
4. Один коммит на обновление, версии ключевых пакетов — в сообщении.
