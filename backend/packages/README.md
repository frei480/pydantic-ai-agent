# Вендоренные .deb-пакеты (офлайн-сборка образа)

Пакеты устанавливаются в `backend/Dockerfile` напрямую через `dpkg -i`,
без обращения к apt-репозиториям: развёртывание идёт в изолированной
сети, и сборка образа не должна зависеть от зеркал Debian.

## Файлы

| Файл | Пакет | Версия | Источник |
| --- | --- | --- | --- |
| `ripgrep_14.1.1-1+b4_amd64.deb` | ripgrep | 14.1.1-1+b4 | Debian 13 (trixie), main/binary-amd64 |
| `libgssapi-krb5-2_1.21.3-5+deb13u1_amd64.deb` | libgssapi-krb5-2 | 1.21.3-5+deb13u1 | Debian 13 (trixie), main/binary-amd64 |
| `libkrb5-3_1.21.3-5+deb13u1_amd64.deb` | libkrb5-3 | 1.21.3-5+deb13u1 | Debian 13 (trixie), main/binary-amd64 |
| `libk5crypto3_1.21.3-5+deb13u1_amd64.deb` | libk5crypto3 | 1.21.3-5+deb13u1 | Debian 13 (trixie), main/binary-amd64 |
| `libkrb5support0_1.21.3-5+deb13u1_amd64.deb` | libkrb5support0 | 1.21.3-5+deb13u1 | Debian 13 (trixie), main/binary-amd64 |
| `libcom-err2_1.47.2-3+b12_amd64.deb` | libcom-err2 | 1.47.2-3+b12 | Debian 13 (trixie), main/binary-amd64 |
| `libkeyutils1_1.6.3-6_amd64.deb` | libkeyutils1 | 1.6.3-6 | Debian 13 (trixie), main/binary-amd64 |

Зависимости ripgrep — `libc6 (>= 2.39)`, `libgcc-s1`, `libpcre2-8-0 (>= 10.22)` —
уже входят в базовый образ `python:3.14-slim` (Debian trixie), поэтому
`dpkg -i` проходит без дополнительных пакетов. krb5-библиотеки — runtime для
доменного входа (python-gssapi): в базовом slim-образе их нет, ставятся
всей группой выше (`libcom-err2`/`libkeyutils1` — общие зависимости).
При смене базового образа (дистрибутив/архитектура) пакеты нужно перекачать
под него.

## Как обновлять

1. Скачать пакет под текущий базовый образ, например через контейнер
   соответствующего дистрибутива:
   `docker run --rm -v <эта папка>:/out debian:trixie sh -c "apt-get update -qq && cd /out && apt-get download ripgrep"`.
2. Обновить версию в таблице выше и в `backend/Dockerfile` (имя файла
   в `COPY`/`dpkg -i` пинится точно).
3. Пересобрать образ и проверить `rg --version` в контейнере.
4. Один коммит на обновление, версия — в сообщении коммита.
