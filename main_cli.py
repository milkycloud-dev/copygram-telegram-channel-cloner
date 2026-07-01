import asyncio
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from copier_core import CopierCore, CopierStats, load_config, save_config
from i18n import t, set_lang

try:
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.align import Align
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

if os.name == 'nt':
    os.system("chcp 65001 > nul")

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def format_duration(seconds: float) -> str:
    """Format duration in seconds to Days Hours:Minutes:Seconds"""
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_phone_from_session(session_path: str) -> str:
    if not os.path.exists(session_path):
        return None
    try:
        import sqlite3
        with sqlite3.connect(session_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT phone FROM entities WHERE phone IS NOT NULL LIMIT 1")
            row = cur.fetchone()
            if row and row[0]:
                return f"+{row[0]}"
    except Exception:
        pass
    return None

def settings_menu(config):
    """
    Displays the interactive settings menu in the CLI and handles user input for modifying the configuration.
    
    Args:
        config (dict): The configuration dictionary loaded from the JSON file.
    """
    while True:
        reader_phone = config.get('reader_phone')
        if not reader_phone:
            reader_phone = get_phone_from_session('session_reader.session')
        reader_disp = reader_phone if reader_phone else t('not_set')
        if os.path.exists('session_reader.session'):
            reader_disp += f" {t('active_session')}"

        creator_phone = config.get('creator_phone')
        if not creator_phone:
            creator_phone = get_phone_from_session('session_creator.session')
        creator_disp = creator_phone if creator_phone else t('not_set')
        if os.path.exists('session_creator.session'):
            creator_disp += f" {t('active_session')}"
            
        print(f"\n{Colors.HEADER}{t('cli_title')}{Colors.ENDC}")
        print(f" 1. {t('api_id')} {config.get('api_id', t('not_set'))}")
        print(f" 2. {t('api_hash')} {config.get('api_hash', t('not_set'))}")
        print(f" 3. {t('acc1_read')} {reader_disp}")
        print(f" 4. {t('acc2_create')} {creator_disp}")
        bot_disp = config.get('bot_token', t('not_set'))
        if os.path.exists('session_bot.session'):
            bot_disp += f" {t('active_session')}"
            
        print(f" 5. {t('bot_token')} {bot_disp}")
        sources = config.get('source_channel_ids', [])
        print(f" 6. {t('sources_queue')} ({len([x for x in sources if x.strip()])})")
        for s in sources:
            if s.strip(): print(f"   - {s}")
        print(f" 7. {t('speed_delay')} {config.get('delay_min', 5.0)} - {config.get('delay_max', 10.0)} {t('sec')} | {t('enabled')} {t('yes') if config.get('enable_delays', True) else t('no')}")
        print(f" 8. {t('create_as_channel')} {t('yes') if config.get('create_as_channel', False) else t('no')}")
        print(f" 9. {t('use_acc1_for_all')} {t('yes') if config.get('use_reader_as_creator', False) else t('no')}")
        print(f"10. {t('reset_progress')}")
        print(f"11. {t('clone_forum_1_to_1')} {t('yes') if config.get('clone_forum_1_to_1', False) else t('no')}")
        print(f"12. {t('watchdog_retries')} {config.get('max_retries', 66)}")
        print(f" 0. {t('save_return')}")
        
        choice = input(f"\n{Colors.OKBLUE}{t('choose_item')} {Colors.ENDC}").strip()
        
        if choice == "1":
            val = input(f"{t('input_api_id')} ").strip()
            if val: config["api_id"] = val
        elif choice == "2":
            val = input(f"{t('input_api_hash')} ").strip()
            if val: config["api_hash"] = val
        elif choice == "3":
            val = input(f"{t('input_phone_read')} ").strip()
            if val: config["reader_phone"] = val
        elif choice == "4":
            val = input(f"{t('input_phone_create')} ").strip()
            if val: config["creator_phone"] = val
        elif choice == "5":
            val = input(f"{t('input_bot_token')} ").strip()
            if val: config["bot_token"] = val
        elif choice == "6":
            print(f"{Colors.WARNING}{t('input_sources_hint')}{Colors.ENDC}")
            print(t('input_sources_hint2'))
            new_sources = []
            while True:
                s = input("> ").strip()
                if not s: break
                new_sources.append(s)
            if new_sources:
                config["source_channel_ids"] = new_sources
                print(f"{Colors.OKGREEN}{t('added_channels', len(new_sources))}{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}{t('queue_not_changed')}{Colors.ENDC}")
        elif choice == "7":
            try:
                en = input(f"{t('use_delays')} ").strip().lower()
                config["enable_delays"] = (en in ["y", "да", "yes"])
                min_v = float(input(f"{t('min_delay')} ").strip())
                max_v = float(input(f"{t('max_delay')} ").strip())
                config["delay_min"] = min_v
                config["delay_max"] = max_v
            except ValueError:
                print(f"{Colors.FAIL}{t('input_err_numbers')}{Colors.ENDC}")
        elif choice == "8":
            curr = config.get("create_as_channel", True)
            config["create_as_channel"] = not curr
            print(f"{Colors.OKGREEN}{t('now_created_as')} {t('channels_ru') if not curr else t('groups_ru')}.{Colors.ENDC}")
        elif choice == "9":
            curr = config.get("use_reader_as_creator", False)
            config["use_reader_as_creator"] = not curr
            print(f"{Colors.OKGREEN}{t('use_one_acc')} {t('yes') if not curr else t('no')}.{Colors.ENDC}")
        elif choice == "10":
            copied = config.get("copied_channels", {})
            if not copied:
                print(f"{Colors.WARNING}{t('progress_empty')}{Colors.ENDC}")
            else:
                print(f"\n{Colors.OKCYAN}{t('saved_progress')}{Colors.ENDC}")
                keys = list(copied.keys())
                for i, k in enumerate(keys):
                    print(f"[{i+1}] Source: {k} | Topics: {len(copied[k].get('topics', {}))}")
                print(f"[{len(keys)+1}] {t('reset_all')}")
                
                src = input(f"\n{Colors.WARNING}{t('reset_prompt')} {Colors.ENDC}").strip()
                if src.isdigit():
                    idx = int(src) - 1
                    if 0 <= idx < len(keys):
                        key = keys[idx]
                        del copied[key]
                        save_config(config)
                        print(f"{Colors.OKGREEN}{t('reset_success', key)}{Colors.ENDC}")
                    elif idx == len(keys):
                        config["copied_channels"] = {}
                        save_config(config)
                        print(f"{Colors.OKGREEN}{t('reset_all_success')}{Colors.ENDC}")
                    else:
                        print(f"{Colors.FAIL}{t('invalid_number')}{Colors.ENDC}")
        elif choice == "11":
            curr = config.get("clone_forum_1_to_1", False)
            config["clone_forum_1_to_1"] = not curr
            print(f"{Colors.OKGREEN}{t('clone_forum_1_to_1')} {t('yes') if not curr else t('no')}.{Colors.ENDC}")
        elif choice == "12":
            try:
                retries = int(input(f"{t('input_retries')} ").strip())
                config["max_retries"] = retries
                print(f"{Colors.OKGREEN}{t('retries_set', retries)}{Colors.ENDC}")
            except ValueError:
                print(f"{Colors.FAIL}{t('input_err_numbers')}{Colors.ENDC}")
        elif choice == "0":
            save_config(config)
            print(f"{Colors.OKGREEN}{t('settings_saved')}{Colors.ENDC}")
            break
        elif choice.lower() == "logs":
            print(f"{Colors.OKCYAN}{t('logs_path')}{Colors.ENDC}")
        else:
            print(t('invalid_choice'))

async def run_copier(config):
    """
    Initializes the CopierCore with the given config and runs the main async loop.
    Sets up the rich Live interface to display logs, stats, and errors.
    
    Args:
        config (dict): The configuration dictionary.
    """
    if not config.get("api_id") or not config.get("api_hash"):
        print(f"{Colors.FAIL}{t('fill_api')}{Colors.ENDC}")
        return
        
    copier = CopierCore()
    
    logger = logging.getLogger("CopierCLI")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler("copier_cli.log", maxBytes=1024*1024*1024, backupCount=1, encoding="utf-8")
        formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if not HAS_RICH:
        print(f"{Colors.FAIL}{t('install_rich')}{Colors.ENDC}")
        return

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="stats", size=7),
        Layout(name="body")
    )
    
    layout["body"].split_row(
        Layout(name="logs", ratio=2),
        Layout(name="errors", ratio=1)
    )
    
    layout["header"].update(Panel(Align.center(t('main_title_rich')), style="blue"))
    
    log_messages = []
    error_messages = []
    media_errors = 0
    system_errors = 0
    current_status = t('init')

    def generate_stats_table(stats: CopierStats, status_msg: str):
        table = Table(show_header=False, expand=True, box=None)
        table.add_column("Key", style="cyan", justify="right")
        table.add_column("Value", style="green", justify="left")
        table.add_column("Key2", style="cyan", justify="right")
        table.add_column("Value2", style="yellow", justify="left")
        
        eta = format_duration(stats.eta_seconds) if stats.eta_seconds and stats.eta_seconds > 0 else "--:--:--"
        table.add_row(
            t('total_msgs'), str(stats.total_channel_msgs),
            t('speed'), f"{stats.current_speed:.1f} /min"
        )
        table.add_row(
            t('sent_msgs'), str(stats.copied_messages),
            t('media_errs'), f"[red]{media_errors}[/red]"
        )
        table.add_row(
            t('created_chats'), str(stats.copied_topics),
            t('sys_errs'), f"[red]{system_errors}[/red]"
        )
        table.add_row(
            t('time_left'), eta,
            t('current_status'), status_msg
        )
        return Panel(table, title=t('stats_title'), border_style="green")

    def generate_log_panel():
        text = "\n".join(log_messages)
        return Panel(text, title=t('log_title'), border_style="blue")
        
    def generate_error_panel():
        text = "\n".join(error_messages)
        return Panel(text, title=t('err_title'), border_style="red")
        
    def update_layout(stats=None):
        if stats is None:
            stats = copier.stats
        if stats is None:
            stats = CopierStats()
        layout["stats"].update(generate_stats_table(stats, current_status))
        layout["logs"].update(generate_log_panel())
        layout["errors"].update(generate_error_panel())

    update_layout()

    with Live(layout, refresh_per_second=2, screen=True) as live:
        def on_log(data):
            nonlocal media_errors, system_errors
            now = datetime.now().strftime("%H:%M:%S")
            if isinstance(data, str):
                from rich.markup import escape
                log_messages.append(f"\\[{now}] {escape(data)}")
                logger.info(data)
            else:
                msg_type = data.get("type", "")
                level = data.get("level", "INFO")
                msg = data.get("msg", "")
                
                if level in ("WARN", "ERROR"):
                    msg_lower = msg.lower()
                    # Simple categorization for metrics
                    if any(x in msg_lower for x in ["media", "album", "file", "send", "медиа", "альбом", "файл", "отправить"]):
                        media_errors += 1
                    else:
                        system_errors += 1
                        
                    from rich.markup import escape
                    safe_msg = escape(msg)
                    if level == "WARN":
                        error_messages.append(f"\\[{now}] [yellow]⚠ {safe_msg}[/yellow]")
                    else:
                        error_messages.append(f"\\[{now}] [red]❌ {safe_msg}[/red]")
                elif msg_type == "bot_send":
                    from rich.markup import escape
                    log_messages.append(f"\\[{now}] [green]✅ {escape(msg)}[/green]")
                else:
                    from rich.markup import escape
                    log_messages.append(f"\\[{now}] {escape(msg)}")
                logger.info(msg)
                
            if len(log_messages) > 15:
                log_messages.pop(0)
            if len(error_messages) > 15:
                error_messages.pop(0)
            update_layout()

        def on_error(msg):
            on_log({"level": "ERROR", "msg": msg})

        def on_status(msg):
            nonlocal current_status
            current_status = msg
            update_layout()

        def on_stats(stats: CopierStats):
            update_layout(stats)

        async def cli_request_input(title, prompt):
            live.stop()
            print(f"\n{Colors.WARNING}{t('req_input', title)}{Colors.ENDC}")
            res = input(f"{prompt} ").strip()
            live.start()
            return res

        copier.on_log = on_log
        copier.on_error = on_error
        copier.on_status = on_status
        copier.on_stats = on_stats
        copier.request_input = cli_request_input
        
        try:
            if not await copier.authorize():
                on_error(t('auth_err'))
            else:
                await copier.start_copy()
                on_status(t('work_done'))
        except KeyboardInterrupt:
            on_status(t('stopping'))
            await copier.stop()
        except Exception as e:
            on_error(t('sys_error', str(e)))
        
        # Delay before exiting so user can read logs
        live.stop()
        print(f"\n{Colors.OKGREEN}{t('press_enter')}{Colors.ENDC}")
        input()

def main():
    """
    Main entry point for the CLI application.
    Loads config, displays the main menu, and orchestrates execution.
    """
    if not os.path.exists("config.json"):
        save_config({})
        
    config = load_config()
    
    # Initialize language
    lang = config.get("language", "ru")
    set_lang(lang)

    while True:
        print(f"\n{Colors.HEADER}{t('cli_main_title')}{Colors.ENDC}")
        print(t('cli_menu_1'))
        print(t('cli_menu_2'))
        print(t('cli_menu_3'))
        print(t('cli_menu_4'))
        
        choice = input(f"\n{Colors.OKBLUE}{t('cli_action')} {Colors.ENDC}").strip()
        
        if choice == "1":
            asyncio.run(run_copier(config))
        elif choice == "2":
            settings_menu(config)
        elif choice == "3":
            # Toggle language
            current = config.get("language", "ru")
            new_lang = "en" if current == "ru" else "ru"
            config["language"] = new_lang
            save_config(config)
            set_lang(new_lang)
            print(f"{Colors.OKGREEN}Language changed to {new_lang.upper()}{Colors.ENDC}")
        elif choice == "4":
            print(f"{Colors.WARNING}{t('goodbye')}{Colors.ENDC}")
            break
        else:
            print(f"{Colors.FAIL}{t('invalid_choice')}{Colors.ENDC}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\nExit.")
