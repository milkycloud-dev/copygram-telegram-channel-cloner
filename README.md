<div align="center">
  <img src="assets/icon.png" width="256" height="256" alt="Copygram Icon">

  # Copygram

  **Clone and mirror Telegram channels into your own.**

  [Русская версия ниже](#русская-версия)

</div>

---

## English Version

**Copygram** clones posts, media and comments from a source Telegram channel into **your own target channel**. It is built on Telethon and copies the feed even where Telegram forbids forwarding.

### Key Features
- **Direct Channel-to-Channel Mirroring**: copies the whole feed of a source channel into your own channel instead of only downloading it.
- **Bypass Protected Content**: Successfully copies and re-uploads media from "Save Restricted" channels straight to your channel.
- **Smart Metadata Cleaning**: Uses FFmpeg and Pillow to modify media hashes (MP4, MOV, GIF, JPG, PNG, OGG). Containers are repackaged without corruption, so Telegram's duplicate file detection does not block the uploads.
- **Multi-Session Support**: Keep your accounts safe by using separate sessions. A "Reader" account monitors the source channel, while a "Creator" account (admin in your target channel) publishes the posts.
- **Dual Interface**: Run in full GUI mode (powered by Flet) for an intuitive visual experience, or CLI mode for headless server environments.
- **Multi-language Support**: Real-time switching between English, Russian, and other localizations.
- **Comment Mirroring**: Optionally clone the discussion from the source channel directly into your target channel's linked discussion group.
- **Delay & Scheduling**: Add realistic delays between posts to simulate human behavior and avoid rate limits (FloodWait).

### Getting Started

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Run Copygram**:
   - **GUI Mode**: `python main_flet.py`
   - **CLI Mode**: `python main_cli.py`
3. **Setup**:
   Follow the on-screen prompts or GUI menus to log into your Reader (the account in the source channel) and Creator (the account with admin rights in your destination channel) sessions.

---

## Русская версия

**Copygram** клонирует Telegram-каналы. Программа не только скачивает файлы, но и **переносит посты, медиа и комментарии из канала-источника в ваш собственный канал**. Работает на Telethon и копирует ленту даже там, где пересылка запрещена.

### Основные возможности
- **Прямое зеркалирование каналов**: Полное клонирование ленты источника и автоматическая публикация контента в вашем канале.
- **Обход защиты от копирования**: Успешно извлекает и перезаливает в ваш канал медиа даже из закрытых источников, где запрещено сохранение и пересылка.
- **Умная очистка метаданных**: Использует FFmpeg и Pillow для изменения хэшей файлов (MP4, MOV, GIF, JPG, PNG, OGG). Алгоритм пересобирает контейнеры без потери качества и повреждений, обходя детекторы дубликатов Telegram при загрузке.
- **Безопасные мульти-сессии**: Разделение ролей для защиты аккаунтов. "Аккаунт-ресивер" только смотрит посты в источнике, а "Аккаунт-креатор" (админ вашего канала) публикует их.
- **Два интерфейса (GUI / CLI)**: Запускайте красивый графический интерфейс (Flet) для удобной работы на ПК, или консольный режим (CLI) для серверов.
- **Мульти-язычность**: Переключение языков интерфейса (Русский/Английский).
- **Клонирование комментариев**: Возможность зеркалирования обсуждений из чата источника напрямую в привязанную группу вашего канала.
- **Защита от блокировок**: Имитация действий реального человека за счёт настраиваемых задержек между постами для предотвращения FloodWait.

### Как начать

1. **Установка зависимостей**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Запуск Copygram**:
   - **Графический интерфейс (GUI)**: `python main_flet.py`
   - **Консольный режим (CLI)**: `python main_cli.py`
3. **Настройка**:
   Интерфейс сам подскажет шаги для авторизации аккаунтов Читателя (состоит в канале-источнике) и Создателя (админ, который будет постить в ваш канал).
