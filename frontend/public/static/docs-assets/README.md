# Локальные ассеты документации API (офлайн)

Статика Swagger UI и ReDoc для страниц `/docs` и `/redoc`, которые бэкенд
отдаёт с относительными URL `/static/docs-assets/...`. Развёртывание идёт в
локальной сети без доступа в интернет, поэтому файлы коммитятся в репозиторий
и раздаются nginx фронтенда (Vite копирует `public/` в `dist` как есть).

## Файлы и версии (скачаны 2026-11-18)

| Файл | Пакет | Версия | Источник |
| --- | --- | --- | --- |
| `js/swagger-ui-bundle.js` | swagger-ui-dist | 5.35.0 | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.35.0/swagger-ui-bundle.js` |
| `css/swagger-ui.css` | swagger-ui-dist | 5.35.0 | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.35.0/swagger-ui.css` |
| `favicon-32x32.png` | swagger-ui-dist | 5.35.0 | `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.35.0/favicon-32x32.png` |
| `js/redoc.standalone.js` | redoc | 2.5.4 | `https://cdn.jsdelivr.net/npm/redoc@2.5.4/bundles/redoc.standalone.js` |

Версии пинятся точно (не плавающий тег `@5`/`@2`), чтобы содержимое папки
соответствовало этой таблице.

## Лицензии

- swagger-ui-dist — Apache License 2.0 (Copyright SmartBear Software).
- redoc — MIT License (Copyright APIs.guru).

## Как обновлять

1. Поднять версию в таблице выше и скачать файлы с URL с точной версией.
2. Проверить `tests/test_docs_offline.py` (`check_docs_offline`) — она
   контролирует и наличие файлов, и отсутствие внешних URL в HTML.
3. Один коммит на обновление, версии — в сообщении коммита.
