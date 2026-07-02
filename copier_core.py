import os
import json
from i18n import t
import asyncio
import time
import random
import shutil
import re
from dataclasses import dataclass
from datetime import datetime
from telethon import TelegramClient, errors, utils
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, InviteToChannelRequest, ToggleForumRequest, EditPhotoRequest
from telethon.tl.functions.messages import GetForumTopicsRequest, CreateForumTopicRequest
from telethon.tl.types import InputChatUploadedPhoto, DocumentAttributeVideo, DocumentAttributeAudio, ChatAdminRights

from metadata_cleaner import clean_file, generate_thumbnail

import csv

CONFIG_FILE = "config.json"
CACHE_DIR = "cache_media"
LOGS_DIR = "logs"
NOT_SENT_DIR = "not_sent"

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(NOT_SENT_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "api_id": 0,
    "api_hash": "",
    "reader_phone": "",
    "creator_phone": "",
    "bot_token": "",
    "source_channel_ids": [""],
    "delay_min": 5.0,
    "delay_max": 10.0,
    "enable_delays": True,
    "use_reader_as_creator": False,
    "create_as_channel": False, # Если False - создает megagroups (группы)
    "clone_forum_1_to_1": False,
    "max_retries": 66,
    "copied_channels": {},
}

def load_config() -> dict:
    """Load configuration from JSON and clean up old/unused keys."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(saved)
        # Migrate old configs
        if "source_channel_id" in cfg and not isinstance(cfg.get("source_channel_ids"), list):
            cfg["source_channel_ids"] = [cfg["source_channel_id"]]
        if "source_channel_ids" not in cfg or not cfg["source_channel_ids"]:
            cfg["source_channel_ids"] = [""]
            
        # Clean up keys not present in DEFAULT_CONFIG (except valid dynamic ones)
        keys_to_keep = set(DEFAULT_CONFIG.keys())
        keys_to_delete = [k for k in cfg.keys() if k not in keys_to_keep]
        for k in keys_to_delete:
            del cfg[k]
            
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_channel_state(config: dict, source_id: str) -> dict:
    channels = config.setdefault("copied_channels", {})
    if source_id not in channels:
        channels[source_id] = {}
        
    state = channels[source_id]
    if "topics" not in state:
        state["topics"] = {}
        
    return state

def get_dir_size(path="."):
    total = 0
    if not os.path.exists(path):
        return 0
    with os.scandir(path) as it:
        for entry in it:
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
            except Exception:
                pass
    return total

def log_to_csv(channel_id: str, row: list):
    """Writes a row to the channel's CSV log file."""
    filepath = os.path.join(LOGS_DIR, f"log_{channel_id}.csv")
    write_header = not os.path.exists(filepath)
    try:
        with open(filepath, "a", encoding="utf-8-sig", newline='') as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["Время", "Old ID", "Old URL", "Медиа", "Статус", "New URL"])
            writer.writerow(row)
    except Exception as e:
        print(f"Failed to write CSV log: {e}")


@dataclass
class CopierStats:
    total_channel_msgs: int = 0
    processed_msgs: int = 0
    start_time: float = 0.0
    copied_topics: int = 0
    copied_messages: int = 0
    eta_seconds: float = 0.0
    current_speed: float = 0.0

class CopierCore:
    """
    Main core class for copying channels/forums in Telegram using Telethon.
    It manages the connection to client accounts (Reader, Creator, and Bot), 
    and handles the logic of downloading media, cleaning metadata, creating
    destinations, and uploading the content.
    """
    def __init__(self, config: dict = None):
        """
        Initializes the CopierCore with the given configuration dictionary.
        Sets up directories and event callbacks.
        """
        self.config = config or load_config()
        self.reader: TelegramClient = None
        self.creator: TelegramClient = None
        self.bot: TelegramClient = None
        
        self.stats = CopierStats()
        self._stop = asyncio.Event()
        self._pause = asyncio.Event()
        self._pause.set()
        
        # Ограничение до 10 потоков для легких картинок
        self._media_semaphore = asyncio.Semaphore(10)
        # Ограничение 1 поток для тяжелых видео/аудио и документов
        self._video_semaphore = asyncio.Semaphore(1)
        self.is_running = False

        self.on_log = None
        self.on_progress_overall = None
        self.on_stats = None
        self.on_status = None
        self.on_complete = None
        self.on_error = None
        self.request_input = None
        
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

    def _make_client(self, session_name: str) -> TelegramClient:
        return TelegramClient(
            session_name,
            int(self.config["api_id"]),
            self.config["api_hash"],
            connection_retries=None, # Infinite wait when internet disconnects
            retry_delay=5,
            auto_reconnect=True,
            request_retries=100, # Huge reserve for requests
            flood_sleep_threshold=60,
        )

    async def connect_all(self) -> bool:
        # Migration of old session
        if os.path.exists("telegram_session.session") and not os.path.exists("session_reader.session"):
            os.rename("telegram_session.session", "session_reader.session")
        if os.path.exists("telegram_session.session-journal") and not os.path.exists("session_reader.session-journal"):
            os.rename("telegram_session.session-journal", "session_reader.session-journal")
        
        # Initialize clients
        if not getattr(self, "reader", None):
            self.reader = self._make_client("session_reader")
            
        if self.config.get("use_reader_as_creator", False):
            self.creator = self.reader
        else:
            # If creator was reader before, but now unchecked, create new client
            if not getattr(self, "creator", None) or self.creator == self.reader:
                self.creator = self._make_client("session_creator")
                
        if not getattr(self, "bot", None):
            self.bot = self._make_client("session_bot")
        
        if not self.reader.is_connected(): await self.reader.connect()
        if not self.creator.is_connected(): await self.creator.connect()
        if not self.bot.is_connected(): await self.bot.connect()
        return True

    async def authorize_client(self, client: TelegramClient, phone_key: str, name_ru: str) -> bool:
        if await client.is_user_authorized():
            return True
            
        print(f"\nАвторизация для {name_ru}")
        method = await self.request_input(t("auth_method", name_ru), t("auth_method_prompt") + " ")
        
        if method == "2":
            import qrcode
            qr_login = await client.qr_login()
            self._emit("on_qr_url", qr_login.url)
            
            # Render QR to console
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.make(fit=True)
            print(t("scan_qr"))
            qr.print_ascii(invert=True)
            
            self._emit("on_status", t("wait_qr"))
            try:
                await qr_login.wait(timeout=120)
                if await client.is_user_authorized():
                    self._emit("on_status", t("qr_success"))
                    return True
            except asyncio.TimeoutError:
                self._emit("on_error", t("qr_timeout"))
                return False
            except Exception as e:
                self._emit("on_error", t("qr_err", str(e)))
                return False
                
        # If phone chosen or QR failed
        phone = self.config.get(phone_key, "").strip()
        if not phone:
            phone = await self.request_input(t("auth_for", name_ru), t("enter_phone"))
            if not phone: return False
            self.config[phone_key] = phone
            save_config(self.config)

        res = await client.send_code_request(phone)
        code = await self.request_input(t("auth_for", name_ru), t("enter_code"))
        if not code: return False

        try:
            await client.sign_in(phone, code.strip(), phone_code_hash=res.phone_code_hash)
        except errors.SessionPasswordNeededError:
            pwd = await self.request_input("2FA", t("enter_2fa"))
            if not pwd: return False
            await client.sign_in(password=pwd)
        except Exception as e:
            self._emit("on_error", t("auth_err_spec", name_ru, str(e)))
            return False
        return True

    async def authorize_bot(self) -> bool:
        if await self.bot.is_user_authorized():
            return True
            
        token = self.config.get("bot_token", "").strip()
        if not token:
            token = await self.request_input("Bot Token", t("enter_bot_token"))
            if not token: return False
            self.config["bot_token"] = token
            save_config(self.config)
            
        try:
            await self.bot.sign_in(bot_token=token)
            return True
        except Exception as e:
            self._emit("on_error", t("bot_err", str(e)))
            return False

    async def authorize(self) -> bool:
        """
        Checks authorization for all required accounts (Reader, Creator, Bot).
        If an account is not authorized, triggers the 'on_error' callback or requests input.
        Returns True if all required accounts are authorized, False otherwise.
        """
        if not self.reader:
            await self.connect_all()

        self._emit("on_status", t("check_auth_reader"))
        if not await self.authorize_client(self.reader, "reader_phone", "Reader (Чтение)"): return False
        
        if self.creator != self.reader:
            self._emit("on_status", t("check_auth_creator"))
            if not await self.authorize_client(self.creator, "creator_phone", "Creator (Создание)"): return False
        
        self._emit("on_status", t("check_auth_bot"))
        if not await self.authorize_bot(): return False

        self._emit("on_status", t("all_auth"))
        return True

    async def disconnect(self):
        if self.reader: await self.reader.disconnect()
        if self.creator: await self.creator.disconnect()
        if self.bot: await self.bot.disconnect()

    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
            self._emit("on_status", "⏸ Пауза...")
            return True
        else:
            self._pause.set()
            self._emit("on_status", "▶ Возобновление работы...")
            return False

    async def start_copy(self):
        """
        Starts the copying process for all source channels defined in the config.
        Iterates over the channels, fetches messages, downloads media, and sends
        them to the destination channel/forum using the bot.
        """
        self._stop.clear()
        self._pause.set()
        self.is_running = True
        try:
            await self._run_copy()
        except asyncio.CancelledError:
            self._emit("on_status", "⏹ Остановлено")
        except Exception as e:
            self._emit("on_error", t("sys_error", str(e)))
            import traceback
            traceback.print_exc()
        finally:
            self.is_running = False
            self._emit("on_complete", None)

    async def stop(self):
        self._stop.set()
        self._pause.set()

    async def _resolve_channel(self, client: TelegramClient, identifier):
        if not identifier: return None
        id_str = str(identifier).strip()
        
        match = re.search(r'(?:t\.me/|t\.me/c/|@)([a-zA-Z0-9_\-]+)', id_str)
        if match:
            id_str = match.group(1)
            
        candidates = []
        
        # Check if the identifier matches our dest_forum_id
        if str(identifier) == str(self.config.get("copied_channels", {}).get("dest_forum_id")):
            raw_id = self.config.get("copied_channels", {}).get("dest_forum_raw_id")
            ahash = self.config.get("copied_channels", {}).get("dest_forum_access_hash")
            if raw_id and ahash:
                from telethon.tl.types import InputPeerChannel
                return InputPeerChannel(channel_id=int(raw_id), access_hash=int(ahash))
                
        if id_str.isdigit() or (id_str.startswith("-") and id_str[1:].isdigit()):
            num = int(id_str)
            candidates.append(num)
            if num > 0:
                candidates.append(int(f"-100{num}"))
                candidates.append(int(f"-{num}"))
        else:
            candidates.append(id_str)
            
        for cand in candidates:
            try:
                return await client.get_entity(cand)
            except Exception:
                pass
                
        try:
            await client.get_dialogs(limit=None)
            for cand in candidates:
                try:
                    return await client.get_entity(cand)
                except Exception:
                    pass
        except: pass
            
        return None

    async def _run_copy(self):
        sources = self.config.get("source_channel_ids", [])
        sources = [s for s in sources if str(s).strip()]
        
        if not sources:
            self._emit("on_error", t("queue_empty"))
            return

        bot_info = await self.bot.get_me()

        for idx, source_id in enumerate(sources):
            if self._stop.is_set():
                break
                
            self._emit("on_status", t("processing_channel", source_id))
            source = await self._resolve_channel(self.reader, source_id)
            if not source: 
                self._emit("on_log", {"level": "ERROR", "msg": t("src_not_found", source_id)})
                continue

            self.stats = CopierStats()
            self.stats.start_time = time.time()
            
            s_id_str = str(utils.get_peer_id(source))
            state = get_channel_state(self.config, s_id_str)
            topics_state = state["topics"]

            # Determine topics
            is_forum = getattr(source, 'forum', False)
            topics = []
            if is_forum:
                self._emit("on_status", t("init"))
                offset_date = 0
                offset_id = 0
                offset_topic = 0
                while True:
                    req = await self.reader(GetForumTopicsRequest(
                        peer=source, offset_date=offset_date, offset_id=offset_id, offset_topic=offset_topic, limit=100
                    ))
                    if not req.topics: break
                    
                    # Filter out deleted topics
                    valid_topics = [t for t in req.topics if hasattr(t, 'date') and hasattr(t, 'top_message')]
                    if not valid_topics: break
                    
                    topics.extend(valid_topics)
                    offset_date = valid_topics[-1].date
                    offset_id = valid_topics[-1].top_message
                    offset_topic = valid_topics[-1].id
                topics.reverse()
            else:
                topics = [{"id": 0, "title": getattr(source, "title", "Main Channel")}]

            total_info = await self.reader.get_messages(source, limit=0)
            self.stats.total_channel_msgs = total_info.total

            for topic in topics:
                if self._stop.is_set(): break
                t_id = getattr(topic, "id", 0)
                t_title = getattr(topic, "title", topic["title"] if isinstance(topic, dict) else "General")
                t_key = str(t_id)

                if t_key not in topics_state:
                    topics_state[t_key] = {"dest_id": "", "last_msg_id": 0, "processed_msgs": 0, "completed": False}
                
                t_state = topics_state[t_key]
                if t_state.get("completed", False):
                    self._emit("on_log", {"level": "INFO", "msg": "Skipping completed topic: " + t_title})
                    continue

                # Create channel/chat via Creator if not created yet
                if not t_state.get("dest_id"):
                    clean_name = t_title.strip()
                    self._emit("on_status", t("creating_chat_for", clean_name))
                    
                    try:
                        if self.config.get("clone_forum_1_to_1", False):
                            dest_forum_id = state.get("dest_forum_id")
                            if not dest_forum_id:
                                # Create common megagroup
                                forum_name = getattr(source, "title", "Main Channel").strip()
                                self._emit("on_status", t("creating_megagroup", forum_name))
                                res = await self.creator(CreateChannelRequest(
                                    title=forum_name, about=f"Mirror of {s_id_str}", megagroup=True
                                ))
                                dest = res.chats[0]
                                dest_forum_id = str(utils.get_peer_id(dest))
                                state["dest_forum_id"] = dest_forum_id
                                state["dest_forum_raw_id"] = dest.id
                                state["dest_forum_access_hash"] = dest.access_hash
                                save_config(self.config)
                                self.stats.copied_topics += 1
                                self._emit("on_log", {"level": "INFO", "msg": f"Создана группа-форум '{forum_name}' (ID: {dest_forum_id})"})
                                
                                # Инвайт бота и права
                                bot_me = await self.bot.get_me()
                                bot_for_creator = await self.creator.get_input_entity(bot_me.username if getattr(bot_me, 'username', None) else bot_me.id)
                                await self.creator(InviteToChannelRequest(dest, [bot_for_creator]))
                                rights = ChatAdminRights(
                                    post_messages=True, edit_messages=True, delete_messages=True,
                                    invite_users=True, pin_messages=True, manage_call=True
                                )
                                await self.creator(EditAdminRequest(dest, bot_for_creator, rights, "bot"))
                                
                                # Включаем режим форума
                                try:
                                    await self.creator(ToggleForumRequest(channel=dest, enabled=True, tabs=False))
                                except Exception as e:
                                    self._emit("on_log", {"level": "WARN", "msg": f"Ошибка включения режима форума: {e}"})

                                await asyncio.sleep(5)
                                try:
                                    await self.bot.get_dialogs(limit=10)
                                except: pass

                            # Теперь создаем тему
                            if t_id == 0 or t_id == 1:
                                t_state["dest_id"] = dest_forum_id
                                t_state["dest_topic_id"] = 1
                            else:
                                self._emit("on_status", f"Создание темы '{clean_name}'...")
                                raw_id = state.get("dest_forum_raw_id")
                                ahash = state.get("dest_forum_access_hash")
                                if raw_id and ahash:
                                    from telethon.tl.types import InputPeerChannel
                                    dest_entity = InputPeerChannel(channel_id=int(raw_id), access_hash=int(ahash))
                                else:
                                    try:
                                        dest_entity = await self.creator.get_entity(int(dest_forum_id))
                                    except ValueError:
                                        self._emit("on_log", {"level": "WARN", "msg": "Чат не найден в кэше, загружаем все диалоги..."})
                                        await self.creator.get_dialogs(limit=None)
                                        dest_entity = await self.creator.get_entity(int(dest_forum_id))
                                res = await self.creator(CreateForumTopicRequest(peer=dest_entity, title=clean_name, random_id=random.randint(1, 2**31), send_as=None, icon_color=0))
                                t_state["dest_id"] = dest_forum_id
                                topic_id = None
                                for update in getattr(res, 'updates', []):
                                    if hasattr(update, "message") and hasattr(update.message, "action"):
                                        topic_id = update.message.id
                                        break
                                if not topic_id: topic_id = 2
                                t_state["dest_topic_id"] = topic_id
                                self._emit("on_log", {"level": "INFO", "msg": f"Создана тема '{clean_name}' (ID: {topic_id})"})
                            
                            save_config(self.config)
                            
                        else:
                            if self.config.get("create_as_channel", True):
                                res = await self.creator(CreateChannelRequest(
                                    title=clean_name, about=f"Mirror of {t_title}", megagroup=False
                                ))
                                dest = res.chats[0]
                            else:
                                res = await self.creator(CreateChannelRequest(
                                    title=clean_name, about=f"Mirror of {t_title}", megagroup=True
                                ))
                                dest = res.chats[0]
                            
                            t_state["dest_id"] = str(utils.get_peer_id(dest))
                            save_config(self.config)
                            self.stats.copied_topics += 1
                            self._emit("on_log", {"level": "INFO", "msg": f"Создан чат '{clean_name}' (ID: {t_state['dest_id']})"})
                            
                            # Инвайт бота
                            self._emit("on_status", "Добавление бота в админы...")
                            bot_me = await self.bot.get_me()
                            if getattr(bot_me, 'username', None):
                                bot_for_creator = await self.creator.get_input_entity(bot_me.username)
                            else:
                                bot_for_creator = await self.creator.get_input_entity(bot_me.id)
                                
                            await self.creator(InviteToChannelRequest(dest, [bot_for_creator]))
                            rights = ChatAdminRights(
                                post_messages=True, edit_messages=True, delete_messages=True,
                                invite_users=True, pin_messages=True, manage_call=True
                            )
                            await self.creator(EditAdminRequest(dest, bot_for_creator, rights, "bot"))
                            
                            # Дадим боту время увидеть чат (увеличим до 5 сек)
                            await asyncio.sleep(5)
                            
                            # Принудительно заставим бота обновить свои чаты
                            try:
                                await self.bot.get_dialogs(limit=10)
                            except: pass
                            
                    except Exception as e:
                        self._emit("on_error", t("create_chat_err", str(e)))
                        import traceback
                        traceback.print_exc()
                        continue

                # Бот должен найти этот чат (ждем до 20 секунд)
                dest_bot = None
                for _ in range(4):
                    dest_bot = await self._resolve_channel(self.bot, int(t_state["dest_id"]))
                    if dest_bot: break
                    await asyncio.sleep(5)
                    try:
                        await self.bot.get_dialogs(limit=10)
                    except: pass
                    
                if not dest_bot:
                    self._emit("on_error", f"Бот не видит чат {t_state['dest_id']}. Telegram задерживает синхронизацию, проверьте права.")
                    continue

                # Начинаем скачивание сообщений
                iter_kw = {"reverse": True}
                if is_forum:
                    iter_kw["reply_to"] = t_id
                
                if t_state["last_msg_id"] > 0:
                    iter_kw["min_id"] = t_state["last_msg_id"]
                    
                self._emit("on_log", {"level": "INFO", "msg": f"▶ Копирование темы: {t_title}"})
                
                processed_this_run = 0
                album_group = []
                
                async def process_album():
                    if album_group:
                        await self._process_and_upload(album_group, dest_bot, source, reply_to=t_state.get("dest_topic_id"))
                        album_group.clear()

                async for message in self.reader.iter_messages(source, **iter_kw):
                    await self._pause.wait()
                    if self._stop.is_set(): break
                    
                    if message.grouped_id:
                        if album_group and album_group[0].grouped_id != message.grouped_id:
                            await process_album()
                        album_group.append(message)
                    else:
                        await process_album()
                        await self._process_and_upload([message], dest_bot, source, reply_to=t_state.get("dest_topic_id"))

                    processed_this_run += 1
                    t_state["last_msg_id"] = message.id
                    t_state["processed_msgs"] += 1
                    self.stats.processed_msgs += 1
                    
                    elapsed = time.time() - self.stats.start_time
                    if elapsed > 0:
                        speed_sec = self.stats.processed_msgs / elapsed
                        self.stats.current_speed = speed_sec * 60
                        msgs_left = self.stats.total_channel_msgs - self.stats.processed_msgs
                        if speed_sec > 0:
                            self.stats.eta_seconds = msgs_left / speed_sec
                        
                    if processed_this_run % 5 == 0:
                        save_config(self.config)
                        self._update_progress(self.stats.processed_msgs)
                        
                await process_album()
                t_state["completed"] = True
                save_config(self.config)
                
            if not self._stop.is_set():
                self._emit("on_log", {"level": "INFO", "msg": f"✅ Завершено клонирование {source_id}"})

        if not self._stop.is_set():
            self._emit("on_status", "✅ Вся очередь клонирования завершена!")

    async def _process_and_upload(self, messages: list, dest_bot, source_chat, reply_to=None):
        # Проверка лимита диска (20 ГБ = cache + not_sent)
        while (get_dir_size(CACHE_DIR) + get_dir_size(NOT_SENT_DIR)) > 20 * 1024 * 1024 * 1024:
            self._emit("on_log", {"level": "WARN", "msg": "Достигнут лимит диска 20 ГБ! Ждем освобождения..."})
            await asyncio.sleep(10)
            
        text_caption = messages[0].message if messages[0].message else ""
        
        media_count = sum(1 for m in messages if m.media)
        if media_count > 0:
            self._emit("on_status", f"Скачивание и обработка {media_count} медиа...")
        elif text_caption:
            self._emit("on_status", "Обработка текстового сообщения...")
        async def process_media_item(msg, index):
            if not msg.media: return None
            
            # Генерация нового имени файла
            file_ext = utils.get_extension(msg.media)
            if not file_ext: file_ext = ".bin"
            new_filename = f"post{msg.id}_{index}{file_ext}"
            custom_path = os.path.join(CACHE_DIR, new_filename)
            
            # Функция для отслеживания времени прогресса
            progress_state = {"last_time": time.time()}
            
            def download_progress(current, total):
                progress_state["last_time"] = time.time()
                if total:
                    pct = current * 100 / total
                    self._emit("on_status", f"Скачивание {new_filename}: {pct:.1f}%")

            async def watchdog(coro):
                task = asyncio.create_task(coro)
                while not task.done():
                    await asyncio.sleep(5)
                    if task.done(): break
                    if time.time() - progress_state["last_time"] > 60:
                        is_online = await asyncio.to_thread(check_internet)
                        if not is_online:
                            self._emit("on_status", "Нет интернета. Ожидание сети...")
                            progress_state["last_time"] = time.time() # сброс таймера
                            continue
                        task.cancel()
                        raise asyncio.TimeoutError("Зависание скачивания")
                return await task

            path = None
            max_dl_attempts = self.config.get("max_retries", 66)
            for attempt in range(1, max_dl_attempts + 1):
                try:
                    progress_state["last_time"] = time.time()
                    path = await watchdog(
                        self.reader.download_media(msg, custom_path, progress_callback=download_progress)
                    )
                    break
                except asyncio.TimeoutError:
                    self._emit("on_log", {"level": "WARN", "msg": f"Таймаут скачивания {new_filename} (попытка {attempt}/{max_dl_attempts})"})
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._emit("on_log", {"level": "WARN", "msg": f"Ошибка скачивания {new_filename}: {e} (попытка {attempt}/{max_dl_attempts})"})
                    await asyncio.sleep(5)
                    
            if not path:
                self._emit("on_log", {"level": "ERROR", "msg": f"Не удалось скачать {new_filename} после {max_dl_attempts} попыток"})
                return None
                
            if not path: return None
            
            # Изменение метаданных
            ext = os.path.splitext(path)[1].lower()
            is_image = ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')
            
            # Разделяем потоки: 10 для картинок, 1 для видео и аудио (чтобы не убить 256MB RAM)
            sem = self._media_semaphore if is_image else self._video_semaphore
            
            async with sem:
                cleaned_path, log_msg, status = await asyncio.to_thread(clean_file, path)
                # Логируем результат
                level = "INFO" if status == "success" else "WARN"
                if status == "error": level = "ERROR"
                self._emit("on_log", {"level": level, "msg": log_msg})
            
            # Определение атрибутов для видео (в т.ч. кружочков) и аудио (в т.ч. голоса)
            attributes = []
            is_video = False
            video_duration = 0
            if hasattr(msg.media, 'document'):
                for attr in msg.media.document.attributes:
                    if isinstance(attr, DocumentAttributeVideo):
                        attributes.append(attr)
                        is_video = True
                        video_duration = attr.duration
                    elif isinstance(attr, DocumentAttributeAudio):
                        attributes.append(attr)
            
            # Генерация миниатюры для видео (превью в Telegram)
            thumb_path = None
            if is_video:
                thumb_path = await asyncio.to_thread(generate_thumbnail, cleaned_path, video_duration)
            
            return {"path": cleaned_path, "attributes": attributes, "thumb": thumb_path}
            
        tasks = [process_media_item(m, i+1) for i, m in enumerate(messages)]
        results = await asyncio.gather(*tasks)
        
        media_files = [r for r in results if r is not None]
                    
        # Загрузка Ботом
        msg_id = messages[0].id
        source_channel_id = str(utils.get_peer_id(source_chat)).replace("-100", "")
        old_url = f"t.me/c/{source_channel_id}/{msg_id}"
        new_url = ""
        status_text = "Skipped"
        
        if media_files or text_caption:
            self._emit("on_status", "Отправка ботом...")
            attempt = 1
            max_attempts = self.config.get("max_retries", 66)
            sent_msg = None
            while attempt <= max_attempts:
                try:
                    progress_state = {"last_time": time.time()}
                    
                    def upload_progress(current, total):
                        progress_state["last_time"] = time.time()
                        if total:
                            pct = current * 100 / total
                            self._emit("on_status", f"Отправка: {pct:.1f}%")
                            
                    async def watchdog_upload(coro):
                        task = asyncio.create_task(coro)
                        while not task.done():
                            await asyncio.sleep(5)
                            if task.done(): break
                            if time.time() - progress_state["last_time"] > 60:
                                is_online = await asyncio.to_thread(check_internet)
                                if not is_online:
                                    self._emit("on_status", "Нет интернета. Ожидание сети...")
                                    progress_state["last_time"] = time.time()
                                    continue
                                task.cancel()
                                raise asyncio.TimeoutError("Зависание отправки")
                        return await task

                    # reply_to already provided as argument

                    progress_state["last_time"] = time.time()
                    if len(media_files) == 1:
                        m = media_files[0]
                        sent_msg = await watchdog_upload(
                            self.bot.send_file(
                                dest_bot, 
                                m["path"], 
                                caption=text_caption, 
                                attributes=m["attributes"] if m["attributes"] else None,
                                thumb=m.get("thumb"),
                                progress_callback=upload_progress,
                                reply_to=reply_to
                            )
                        )
                    elif len(media_files) > 1:
                        # Альбомы: загружаем каждый файл с правильными атрибутами и превью
                        uploaded_files = []
                        for m in media_files:
                            uploaded_files.append({
                                "file": m["path"],
                                "attributes": m["attributes"] if m["attributes"] else None,
                                "thumb": m.get("thumb")
                            })
                        
                        # Отправляем альбом, передавая атрибуты для каждого файла
                        # Telethon поддерживает список файлов, но не per-file атрибуты,
                        # поэтому загружаем по одному файлу, если есть атрибуты
                        has_attrs = any(uf["attributes"] for uf in uploaded_files)
                        if has_attrs:
                            # Отправляем по одному файлу с правильными атрибутами
                            sent_msgs = []
                            for idx, uf in enumerate(uploaded_files):
                                cap = text_caption if idx == 0 else None
                                s = await watchdog_upload(
                                    self.bot.send_file(
                                        dest_bot, uf["file"],
                                        caption=cap,
                                        attributes=uf["attributes"],
                                        thumb=uf.get("thumb"),
                                        progress_callback=upload_progress,
                                        reply_to=reply_to
                                    )
                                )
                                sent_msgs.append(s)
                            sent_msg = sent_msgs[0]
                        else:
                            files = [m["path"] for m in media_files]
                            thumbs = [m.get("thumb") for m in media_files]
                            sent_msg = await watchdog_upload(
                                self.bot.send_file(dest_bot, files, caption=text_caption, thumb=thumbs, progress_callback=upload_progress, reply_to=reply_to)
                            )
                    else:
                        sent_msg = await self.bot.send_message(dest_bot, text_caption, reply_to=reply_to)
                        
                    self.stats.copied_messages += len(messages)
                    self._emit("on_log", {"type": "bot_send", "msg": f"Бот отправил пост (медиа: {len(media_files)})"})
                    status_text = "Success"
                    
                    if isinstance(sent_msg, list): sent_msg = sent_msg[0]
                    if sent_msg:
                        dest_channel_id = str(utils.get_peer_id(dest_bot)).replace("-100", "")
                        new_url = f"t.me/c/{dest_channel_id}/{sent_msg.id}"
                        self._emit("on_log", {"level": "INFO", "msg": f"🔗 Отправлен пост: {new_url} (оригинал: {old_url})"})
                    break
                    
                except errors.FloodWaitError as e:
                    wait = e.seconds * 1.5
                    self._emit("on_log", {"level": "WARN", "msg": f"FloodWait Бота: {wait} сек (попытка {attempt}/{max_attempts})"})
                    await asyncio.sleep(wait)
                    attempt += 1
                except asyncio.TimeoutError:
                    self._emit("on_log", {"level": "WARN", "msg": f"Таймаут (зависание) при отправке. (попытка {attempt}/{max_attempts})"})
                    attempt += 1
                except Exception as e:
                    delay = random.uniform(20.0, 60.0)
                    self._emit("on_log", {"level": "WARN", "msg": f"Ошибка отправки: {e}. Ждем {delay:.1f} сек (попытка {attempt}/{max_attempts})"})
                    await asyncio.sleep(delay)
                    attempt += 1
                    
            if attempt > max_attempts:
                status_text = "Failed"
                self._emit("on_log", {"level": "ERROR", "msg": f"Не удалось отправить пост {old_url} после {max_attempts} попыток."})
                
        # Логирование в CSV
        log_to_csv(source_channel_id, [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            msg_id,
            old_url,
            len(media_files),
            status_text,
            new_url
        ])
                
        # Clean up локальных файлов или перенос в not_sent
        for m in media_files:
            try:
                if status_text == "Success":
                    os.remove(m["path"])
                    if m.get("thumb") and os.path.exists(m["thumb"]):
                        os.remove(m["thumb"])
                elif status_text == "Failed":
                    filename = os.path.basename(m["path"])
                    shutil.move(m["path"], os.path.join(NOT_SENT_DIR, filename))
                    self._emit("on_log", {"level": "WARN", "msg": f"Медиа {filename} сохранено в not_sent/"})
                    if m.get("thumb") and os.path.exists(m["thumb"]):
                        os.remove(m["thumb"])
            except: pass
            
        if status_text == "Success" and media_files:
            self._emit("on_log", {"level": "INFO", "msg": f"🗑 Очистка локального кэша для поста {msg_id} завершена"})
            
        # Задержка
        if self.config.get("enable_delays", True):
            delay = random.uniform(self.config.get("delay_min", 5.0), self.config.get("delay_max", 10.0))
            self._emit("on_status", f"Задержка {delay:.2f} сек...")
            await asyncio.sleep(delay)

    def _update_progress(self, done: int):
        total = self.stats.total_channel_msgs
        frac = done / total if total > 0 else 0.0
        self._emit("on_progress_overall", frac, done, total)

    def _emit(self, name: str, *args):
        cb = getattr(self, name, None)
        if cb:
            try:
                cb(*args)
            except Exception:
                pass
