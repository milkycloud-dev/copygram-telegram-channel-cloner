<p align="center"><img src="assets/icon.png" width="128" height="128" alt="Copygram icon"></p>

<h1 align="center">Copygram</h1>

<p align="center">Desktop and CLI tool that copies a Telegram channel or forum group, posts, albums, media and comments, into a channel you own. Built on Telethon, with a Flet interface. Windows and Linux.</p>

<p align="center"><a href="https://github.com/milkycloud-dev/copygram-telegram-channel-cloner/actions/workflows/release.yml"><img src="https://github.com/milkycloud-dev/copygram-telegram-channel-cloner/actions/workflows/release.yml/badge.svg" alt="Release"></a></p>

<p align="center"><a href="#english">English</a> | <a href="#русский">Русский</a></p>

<a id="english"></a>

## English

### What it does

Copygram reads a source channel with one Telegram account and republishes its history into a destination channel with another account or a bot. Media is downloaded and uploaded again, so the copy does not depend on forwarding. Progress is kept per source channel, so a stopped run continues where it ended.

### Features

- Several source channels in one config; each keeps its own position.
- The destination channel or megagroup is created on the first run; a forum group can be cloned topic by topic.
- Albums stay albums; video gets its duration and a thumbnail from the middle of the clip.
- Comments from the source discussion group can be copied into the linked group of the destination.
- Media files are repackaged with FFmpeg and Pillow before upload (MP4, MOV, GIF, JPG, PNG, OGG), which changes their hash without re-encoding.
- Separate reader and creator sessions, or one account for both; uploads through a bot token are supported.
- Random delays between posts and a retry limit against `FloodWait`.
- Posts that could not be sent go to `not_sent/`, every copied post is logged to CSV in `logs/`.
- Interface in English and Russian, switched without restart.

### Quick start

```bash
pip install -r requirements.txt
python main_flet.py   # window
python main_cli.py    # terminal
```

On first start enter the Telegram `api_id` and `api_hash` from my.telegram.org, the phone numbers of the reader and creator accounts (or a bot token) and the source channel ids. Everything is saved to `config.json`; sessions are stored next to it as `*.session`. Neither file should be shared or committed.

### Configuration

| Key | Default | Meaning |
|---|---|---|
| `source_channel_ids` | `[""]` | channels to copy, by id or username |
| `delay_min`, `delay_max`, `enable_delays` | `5`, `10`, `true` | random pause between posts, seconds |
| `use_reader_as_creator` | `false` | one account reads and publishes |
| `create_as_channel` | `false` | create a channel instead of a megagroup |
| `clone_forum_1_to_1` | `false` | recreate forum topics one to one |
| `max_retries` | `66` | attempts per post before it goes to `not_sent/` |

### Responsible use

Copy only what you have the right to copy: your own channels, backups, content whose owner agreed. Telegram accounts that mass-repost other people's content can be limited or banned.

### Releases

A tag `v*` builds `Copygram_Windows.zip` and `Copygram_Linux.tar.gz` with PyInstaller on GitHub Actions and publishes them with the notes from [CHANGELOG.md](CHANGELOG.md).

### License

Proprietary, all rights reserved. Running the official release builds is allowed; see [LICENSE](LICENSE) for the full terms.

<a id="русский"></a>

## Русский

### Что делает

Copygram читает канал-источник одним аккаунтом Telegram и публикует его историю в канал-назначение другим аккаунтом или ботом. Медиа скачиваются и загружаются заново, поэтому копия не зависит от пересылки. Позиция хранится для каждого источника отдельно, остановленный прогон продолжается с того же места.

### Возможности

- Несколько каналов-источников в одном конфиге, у каждого своя позиция.
- Канал или мегагруппа назначения создаются при первом запуске; группу-форум можно склонировать по темам.
- Альбомы остаются альбомами; у видео сохраняется длительность и превью из середины ролика.
- Комментарии из группы обсуждения источника можно перенести в привязанную группу назначения.
- Перед загрузкой файлы перепаковываются через FFmpeg и Pillow (MP4, MOV, GIF, JPG, PNG, OGG): хэш меняется без перекодирования.
- Раздельные сессии читателя и создателя или один аккаунт на обе роли; поддерживается загрузка через токен бота.
- Случайные паузы между постами и лимит повторов на случай `FloodWait`.
- Посты, которые не удалось отправить, складываются в `not_sent/`, каждый скопированный пост пишется в CSV в `logs/`.
- Интерфейс на английском и русском, переключается без перезапуска.

### Быстрый старт

```bash
pip install -r requirements.txt
python main_flet.py   # окно
python main_cli.py    # терминал
```

При первом запуске введите `api_id` и `api_hash` Telegram с my.telegram.org, номера аккаунтов читателя и создателя (или токен бота) и id каналов-источников. Всё сохраняется в `config.json`, сессии лежат рядом в файлах `*.session`. Эти файлы нельзя передавать и коммитить.

### Настройки

| Ключ | По умолчанию | Значение |
|---|---|---|
| `source_channel_ids` | `[""]` | каналы для копирования, по id или username |
| `delay_min`, `delay_max`, `enable_delays` | `5`, `10`, `true` | случайная пауза между постами, секунды |
| `use_reader_as_creator` | `false` | один аккаунт читает и публикует |
| `create_as_channel` | `false` | создавать канал, а не мегагруппу |
| `clone_forum_1_to_1` | `false` | повторять темы форума один к одному |
| `max_retries` | `66` | попыток на пост, после чего он уходит в `not_sent/` |

### Ответственное использование

Копируйте только то, на что у вас есть право: свои каналы, резервные копии, материалы с согласия владельца. Аккаунты, которые массово перепостят чужое, Telegram может ограничить или заблокировать.

### Релизы

Тег `v*` собирает `Copygram_Windows.zip` и `Copygram_Linux.tar.gz` через PyInstaller в GitHub Actions и публикует их с описанием из [CHANGELOG.md](CHANGELOG.md).

### Лицензия

Проприетарная, все права защищены. Запуск официальных сборок из релизов разрешён; полные условия в [LICENSE](LICENSE).
