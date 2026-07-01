import flet as ft
import asyncio
import os
import io
import time
from datetime import datetime
from copier_core import CopierCore, CopierStats, save_config, load_config
from i18n import t, set_lang, get_lang

def format_duration(seconds: float) -> str:
    """Format duration in seconds to Days Hours:Minutes:Seconds"""
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

class TelegramCopierFlet:
    """
    Flet GUI application for Telegram Channel Copier.
    Handles the UI layout, state management, and bindings to CopierCore.
    """
    def __init__(self, page: ft.Page):
        """
        Initializes the UI application.
        
        Args:
            page (ft.Page): The main Flet page instance.
        """
        self.page = page
        self.page.title = "Telegram Channel Copier"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window_width = 1100
        self.page.window_height = 850
        self.page.padding = 0
        self.page.fonts = {
            "Inter": "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.woff2",
            "InterBold": "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.woff2"
        }
        self.page.theme = ft.Theme(font_family="Inter")

        self.copier = CopierCore()
        
        # Load language from config
        lang = self.copier.config.get("language", "ru")
        set_lang(lang)

        self.bind_callbacks()

        self.stat_labels = {}
        self.log_entries = []
        
        self.source_fields_column = ft.Column(spacing=10)

        self.build_ui()
        self.load_settings()
        
        self.page.run_task(self.check_auth_on_startup)
        
    def toggle_language(self, e):
        current = self.copier.config.get("language", "ru")
        new_lang = "en" if current == "ru" else "ru"
        self.copier.config["language"] = new_lang
        save_config(self.copier.config)
        set_lang(new_lang)
        
        self.page.controls.clear()
        self.build_ui()
        self.load_settings()
        self.page.run_task(self.check_auth_on_startup)
        self.page.update()

    async def check_auth_on_startup(self, *args):
        try:
            await self.copier.connect_all()
            
            # Reset to not authorized by default if they fail check
            self.lbl_reader_auth.value = t("auth_reader_fail")
            self.lbl_reader_auth.color = ft.colors.RED_400
            self.lbl_creator_auth.value = t("auth_creator_fail")
            self.lbl_creator_auth.color = ft.colors.RED_400
            self.lbl_bot_auth.value = t("auth_bot_fail")
            self.lbl_bot_auth.color = ft.colors.RED_400
            
            # Check Reader
            if await self.copier.reader.is_user_authorized():
                try:
                    me = await self.copier.reader.get_me()
                    phone = getattr(me, 'phone', '')
                    self.lbl_reader_auth.value = f"{t('auth_reader_ok')} (+{phone})"
                    if phone:
                        self.inp_reader.value = f"+{phone}"
                except Exception:
                    self.lbl_reader_auth.value = t("auth_reader_ok")
                self.lbl_reader_auth.color = ft.colors.GREEN_400

            # Check Creator
            if getattr(self.copier, "creator", None) and await self.copier.creator.is_user_authorized():
                try:
                    me = await self.copier.creator.get_me()
                    phone = getattr(me, 'phone', '')
                    self.lbl_creator_auth.value = f"{t('auth_creator_ok')} (+{phone})"
                    if phone:
                        self.inp_creator.value = f"+{phone}"
                except Exception:
                    self.lbl_creator_auth.value = t("auth_creator_ok")
                self.lbl_creator_auth.color = ft.colors.GREEN_400

            # Check Bot
            if await self.copier.bot.is_user_authorized():
                try:
                    me = await self.copier.bot.get_me()
                    username = getattr(me, 'username', 'Bot')
                    self.lbl_bot_auth.value = f"{t('auth_bot_ok')} (@{username})"
                except Exception:
                    self.lbl_bot_auth.value = t("auth_bot_ok")
                self.lbl_bot_auth.color = ft.colors.GREEN_400

            self.page.update()
        except Exception as e:
            self.write_auth_log(t("auth_error_start", str(e)))

    def bind_callbacks(self):
        c = self.copier
        c.on_status = self.cb_status
        c.on_error = self.cb_error
        c.on_qr_url = self.cb_qr
        c.on_complete = self.cb_complete
        c.on_progress_overall = self.cb_progress_overall
        c.on_log = self.cb_log
        c.on_stats = self.cb_stats
        c.request_input = self.cb_request_input

    def build_ui(self):
        """
        Builds and structures the overall Flet user interface.
        """
        self.btn_lang = ft.ElevatedButton(t("language_toggle"), on_click=self.toggle_language, color=ft.colors.BLUE_400)
        
        header = ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.icons.COPY_ALL, size=30, color=ft.colors.BLUE_400),
                    ft.Text("Telegram Channel Copier", size=24, weight=ft.FontWeight.BOLD, font_family="InterBold"),
                ], alignment=ft.MainAxisAlignment.START, expand=1),
                self.btn_lang
            ]),
            padding=15,
            bgcolor=ft.colors.SURFACE_VARIANT,
            border_radius=ft.border_radius.only(bottom_left=15, bottom_right=15)
        )

        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text=t("flet_auth"), content=self.build_auth_tab()),
                ft.Tab(text=t("flet_copy"), content=self.build_copy_tab()),
                ft.Tab(text=t("flet_logs"), content=self.build_logs_tab()),
                ft.Tab(text=t("flet_settings"), content=self.build_settings_tab()),
            ],
            expand=1,
        )

        self.lbl_global_status = ft.Text(t("not_authorized"), color=ft.colors.RED_400)
        
        # Load CSV logs on startup
        self.refresh_log_files()
        
        status_bar = ft.Container(
            content=ft.Row([
                self.lbl_global_status
            ]),
            padding=10,
            bgcolor=ft.colors.SURFACE_VARIANT
        )

        self.page.add(
            ft.Column([header, self.tabs, status_bar], expand=True)
        )

    def build_auth_tab(self):
        self.img_qr = ft.Image(width=200, height=200, visible=False)
        
        self.lbl_reader_auth = ft.Text(t("loading_sessions"), color=ft.colors.ORANGE_400)
        self.btn_reader_auth = ft.ElevatedButton(t("login_reader"), on_click=self.on_auth_reader, icon=ft.icons.LOGIN, bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)
        
        self.lbl_creator_auth = ft.Text(t("loading_sessions"), color=ft.colors.ORANGE_400)
        self.btn_creator_auth = ft.ElevatedButton(t("login_creator"), on_click=self.on_auth_creator, icon=ft.icons.LOGIN, bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)
        
        self.lbl_bot_auth = ft.Text(t("loading_sessions"), color=ft.colors.ORANGE_400)
        self.btn_bot_auth = ft.ElevatedButton(t("login_bot"), on_click=self.on_auth_bot, icon=ft.icons.LOGIN, bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)
        
        self.txt_auth_log = ft.ListView(expand=True, spacing=5, padding=10)
        log_container = ft.Container(
            content=self.txt_auth_log,
            bgcolor=ft.colors.BACKGROUND,
            border=ft.border.all(1, ft.colors.OUTLINE),
            border_radius=10,
            height=200
        )

        return ft.Container(
            content=ft.Column([
                ft.Text(t("auth_title"), size=20, weight=ft.FontWeight.BOLD),
                ft.Text(t("auth_desc"), color=ft.colors.GREY_400),
                
                ft.Row([
                    self.btn_reader_auth,
                    self.btn_creator_auth,
                    self.btn_bot_auth,
                ]),
                
                ft.ElevatedButton(t("logout_all"), on_click=self.on_logout, icon=ft.icons.LOGOUT, color=ft.colors.RED_400),
                
                ft.Container(
                    content=ft.Column([self.lbl_reader_auth, self.lbl_creator_auth, self.lbl_bot_auth]),
                    padding=10,
                    bgcolor=ft.colors.SURFACE_VARIANT,
                    border_radius=5
                ),
                ft.Container(self.img_qr, alignment=ft.alignment.center, padding=10),
                ft.Text(t("auth_log"), weight=ft.FontWeight.BOLD),
                log_container
            ], scroll=ft.ScrollMode.AUTO),
            padding=20
        )

    def build_copy_tab(self):
        self.pb_main = ft.ProgressBar(value=0, height=10, color=ft.colors.GREEN_400, bgcolor=ft.colors.SURFACE_VARIANT)
        self.lbl_progress = ft.Text(t("overall_progress", 0, 0), size=14)
        
        prog_card = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(t("current_progress"), weight=ft.FontWeight.BOLD, size=16),
                    self.pb_main,
                    self.lbl_progress,
                ]),
                padding=20
            ),
            elevation=4
        )

        stats_keys = [
            ("total_msgs", t("total_msgs")),
            ("processed", t("processed")),
            ("topics", t("created_topics")),
            ("copied_msgs", t("sent_by_bot")),
            ("elapsed", t("elapsed_time")),
            ("eta", t("eta_time")),
        ]
        
        grid_items = []
        for key, title in stats_keys:
            val_text = ft.Text("0", size=18, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_400)
            self.stat_labels[key] = val_text
            card = ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(title, size=12, color=ft.colors.GREY_400),
                        val_text
                    ], alignment=ft.MainAxisAlignment.CENTER),
                    padding=10,
                    width=150
                )
            )
            grid_items.append(card)

        stats_grid = ft.Row(grid_items, wrap=True, alignment=ft.MainAxisAlignment.START)

        self.btn_pause = ft.ElevatedButton(t("btn_pause"), on_click=self.on_pause, icon=ft.icons.PAUSE, color=ft.colors.ORANGE_400)

        controls = ft.Row([
            ft.ElevatedButton(t("btn_start"), on_click=self.on_start_dl, icon=ft.icons.PLAY_ARROW, bgcolor=ft.colors.GREEN_600, color=ft.colors.WHITE),
            self.btn_pause,
            ft.ElevatedButton(t("btn_stop"), on_click=self.on_stop_dl, icon=ft.icons.STOP, bgcolor=ft.colors.RED_600, color=ft.colors.WHITE),
            ft.ElevatedButton(t("btn_reset_cache"), on_click=self.on_reset, icon=ft.icons.REFRESH, color=ft.colors.GREY_400),
        ])

        self.live_log_list = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        live_log_card = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(t("live_log_title"), weight=ft.FontWeight.BOLD),
                    ft.Container(self.live_log_list, expand=True)
                ]),
                padding=10,
                expand=True
            ),
            expand=True
        )

        return ft.Container(
            content=ft.Column([
                controls,
                prog_card,
                ft.Text(t("stats_tab_title"), size=18, weight=ft.FontWeight.BOLD),
                stats_grid,
                live_log_card
            ]),
            padding=20,
            expand=True
        )

    def build_logs_tab(self):
        self.logs_dropdown = ft.Dropdown(
            label=t("choose_log"), 
            options=[], 
            width=300,
            on_change=self.on_log_select
        )
        self.btn_refresh_logs = ft.IconButton(icon=ft.icons.REFRESH, on_click=self.refresh_log_files)
        
        self.logs_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text(t("time_col"))),
                ft.DataColumn(ft.Text(t("old_url_col"))),
                ft.DataColumn(ft.Text(t("new_url_col"))),
                ft.DataColumn(ft.Text(t("media_col"))),
                ft.DataColumn(ft.Text(t("status_col"))),
            ],
            rows=[]
        )
        
        self.logs_listview = ft.ListView(expand=True, spacing=10, auto_scroll=False)
        self.logs_listview.controls.append(
            ft.Row([self.logs_table], scroll=ft.ScrollMode.AUTO)
        )
        
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Text(t("detailed_log"), size=18, weight=ft.FontWeight.BOLD), self.btn_refresh_logs]),
                self.logs_dropdown,
                ft.Container(
                    content=self.logs_listview, 
                    expand=True, 
                    padding=10, 
                    bgcolor=ft.colors.BACKGROUND,
                    border=ft.border.all(1, ft.colors.OUTLINE), 
                    border_radius=10
                )
            ]),
            padding=20,
            expand=True
        )
        
    def refresh_log_files(self, e=None):
        if not os.path.exists("logs"): return
        files = [f for f in os.listdir("logs") if f.endswith(".csv")]
        self.logs_dropdown.options = [ft.dropdown.Option(f) for f in files]
        self.page.update()
        
    def on_log_select(self, e):
        filename = self.logs_dropdown.value
        if not filename: return
        filepath = os.path.join("logs", filename)
        if not os.path.exists(filepath): return
        
        rows = []
        import csv
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for r in reader:
                    if len(r) >= 6:
                        # Time, Old ID, Old URL, Media, Status, New URL
                        cells = [
                            ft.DataCell(ft.Text(r[0])),
                            ft.DataCell(ft.Text(r[2], selectable=True)),
                            ft.DataCell(ft.Text(r[5], selectable=True)),
                            ft.DataCell(ft.Text(r[3])),
                            ft.DataCell(ft.Text(r[4], color=ft.colors.GREEN_400 if r[4]=="Success" else ft.colors.RED_400)),
                        ]
                        rows.append(ft.DataRow(cells=cells))
        except Exception as ex:
            print(f"Error reading csv: {ex}")
            
        self.logs_table.rows = rows
        self.page.update()

    def build_settings_tab(self):
        self.inp_api_id = ft.TextField(label="API ID")
        self.inp_api_hash = ft.TextField(label="API Hash", password=True, can_reveal_password=True)
        
        self.sw_use_reader_as_creator = ft.Switch(label=t("use_acc1_for_all"), value=False, on_change=self.on_save_settings)
        self.inp_reader = ft.TextField(label=t("acc1_read"))
        self.inp_creator = ft.TextField(label=t("acc2_create"))
        self.inp_bot = ft.TextField(label=t("bot_token"))
        
        self.sw_channel = ft.Switch(label=t("create_as_channel"))
        self.sw_clone_forum = ft.Switch()
        self.row_clone_forum = ft.Row([self.sw_clone_forum, ft.Text(t("clone_forum_1_to_1"), expand=True)])
        self.inp_max_retries = ft.TextField(label=t("watchdog_retries"), width=150)
        self.btn_reset_progress = ft.ElevatedButton(t("reset_progress"), on_click=self.on_reset_progress, color=ft.colors.RED_400)
        
        btn_add_source = ft.ElevatedButton(t("btn_add_source"), on_click=self.on_add_source, color=ft.colors.BLUE_400)
        
        self.lbl_delay = ft.Text(t("random_delay"), weight=ft.FontWeight.BOLD)
        
        self.sw_enable_delays = ft.Switch(label=t("use_delays_flet"), value=True, on_change=self.on_save_settings)
        self.inp_delay_min = ft.TextField(label=t("min_delay_flet"), value="5.0", width=150, on_change=self.on_delay_change)
        self.inp_delay_max = ft.TextField(label=t("max_delay_flet"), value="10.0", width=150, on_change=self.on_delay_change)
        
        delay_row = ft.Row([self.inp_delay_min, self.inp_delay_max])
        
        btn_save = ft.ElevatedButton(t("btn_save_settings"), on_click=self.on_save_settings, bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)

        return ft.Container(
            content=ft.Column([
                ft.Text(t("settings_api_title"), size=18, weight=ft.FontWeight.BOLD),
                self.inp_api_id,
                self.inp_api_hash,
                self.sw_use_reader_as_creator,
                self.inp_reader,
                self.inp_creator,
                self.inp_bot,
                self.sw_channel,
                self.row_clone_forum,
                self.inp_max_retries,
                self.btn_reset_progress,
                ft.Divider(),
                
                ft.Text(t("settings_queue_title"), size=18, weight=ft.FontWeight.BOLD),
                ft.Text(t("settings_queue_desc"), color=ft.colors.GREY_400),
                self.source_fields_column,
                btn_add_source,
                
                ft.Divider(),
                ft.Text(t("settings_speed_title"), size=18, weight=ft.FontWeight.BOLD),
                self.sw_enable_delays,
                self.lbl_delay,
                delay_row,
                ft.Text(t("delay_warning"), size=12, color=ft.colors.ORANGE_400),
                
                ft.Divider(),
                btn_save
            ], scroll=ft.ScrollMode.AUTO),
            padding=20
        )

    def create_source_row(self, initial_value=""):
        txt = ft.TextField(label=t("source_placeholder"), value=initial_value, expand=True)
        btn_del = ft.IconButton(ft.icons.DELETE, icon_color=ft.colors.RED_400, on_click=lambda e: self.on_del_source(row))
        row = ft.Row([txt, btn_del])
        return row

    def on_add_source(self, e):
        self.source_fields_column.controls.append(self.create_source_row())
        self.page.update()

    def on_del_source(self, row):
        if len(self.source_fields_column.controls) > 1:
            self.source_fields_column.controls.remove(row)
            self.page.update()

    def on_delay_change(self, e):
        pass

    def load_settings(self):
        cfg = self.copier.config
        self.inp_api_id.value = str(cfg.get("api_id", ""))
        self.inp_api_hash.value = cfg.get("api_hash", "")
        
        self.sw_use_reader_as_creator.value = self.copier.config.get("use_reader_as_creator", False)
        
        def get_phone(session_path):
            import sqlite3
            import os
            if not os.path.exists(session_path): return ""
            try:
                with sqlite3.connect(session_path) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT phone FROM entities WHERE phone IS NOT NULL LIMIT 1")
                    row = cur.fetchone()
                    if row and row[0]: return f"+{row[0]}"
            except Exception: pass
            return ""

        reader_phone = cfg.get("reader_phone", "")
        if not reader_phone: reader_phone = get_phone('session_reader.session')
        self.inp_reader.value = reader_phone
        
        creator_phone = cfg.get("creator_phone", "")
        if not creator_phone: creator_phone = get_phone('session_creator.session')
        self.inp_creator.value = creator_phone
        self.inp_bot.value = self.copier.config.get("bot_token", "")
        self.sw_channel.value = self.copier.config.get("create_as_channel", False)
        self.sw_enable_delays.value = self.copier.config.get("enable_delays", True)
        self.sw_clone_forum.value = self.copier.config.get("clone_forum_1_to_1", False)
        self.inp_max_retries.value = str(self.copier.config.get("max_retries", 66))
        
        # Update Creator field visibility
        self.inp_creator.visible = not self.sw_use_reader_as_creator.value
        if getattr(self, 'btn_creator_auth', None):
            self.btn_creator_auth.disabled = self.sw_use_reader_as_creator.value
        
        self.source_fields_column.controls.clear()
        sources = cfg.get("source_channel_ids", [""])
        if not sources: sources = [""]
        for s in sources:
            self.source_fields_column.controls.append(self.create_source_row(s))
            
        d_min = float(cfg.get("delay_min", 5.0))
        d_max = float(cfg.get("delay_max", 10.0))
        self.inp_delay_min.value = str(d_min)
        self.inp_delay_max.value = str(d_max)
        
        self.page.update()

    def on_save_settings(self, e):
        cfg = self.copier.config
        cfg["api_id"] = int(self.inp_api_id.value) if self.inp_api_id.value.isdigit() else 0
        cfg["api_hash"] = self.inp_api_hash.value
        self.copier.config["use_reader_as_creator"] = self.sw_use_reader_as_creator.value
        cfg["reader_phone"] = self.inp_reader.value
        self.copier.config["creator_phone"] = self.inp_creator.value.strip()
        
        # Update Creator field visibility
        self.inp_creator.visible = not self.sw_use_reader_as_creator.value
        if getattr(self, 'btn_creator_auth', None):
            self.btn_creator_auth.disabled = self.sw_use_reader_as_creator.value
        self.copier.config["bot_token"] = self.inp_bot.value.strip()
        self.copier.config["create_as_channel"] = self.sw_channel.value
        self.copier.config["enable_delays"] = self.sw_enable_delays.value
        self.copier.config["clone_forum_1_to_1"] = self.sw_clone_forum.value
        try:
            self.copier.config["max_retries"] = int(self.inp_max_retries.value)
        except ValueError:
            pass
        
        sources = []
        for row in self.source_fields_column.controls:
            txt = row.controls[0].value.strip()
            if txt:
                sources.append(txt)
        if not sources: sources = [""]
        cfg["source_channel_ids"] = sources
        
        try:
            cfg["delay_min"] = float(self.inp_delay_min.value)
            cfg["delay_max"] = float(self.inp_delay_max.value)
        except ValueError:
            pass
        
        save_config(cfg)
        self.write_log(t("settings_saved_flet"), ft.colors.GREEN_400)
        self.page.snack_bar = ft.SnackBar(ft.Text(t("settings_saved_flet")))
        self.page.snack_bar.open = True
        self.page.update()

    def on_reset_progress(self, e):
        self.copier.config["copied_channels"] = {}
        from copier_core import save_config
        save_config(self.copier.config)
        self.page.snack_bar = ft.SnackBar(ft.Text(t("reset_all_success")))
        self.page.snack_bar.open = True
        self.page.update()

    def write_log(self, text, color=ft.colors.GREY_300):
        ts = datetime.now().strftime("%H:%M:%S")
        self.live_log_list.controls.append(ft.Text(f"[{ts}] {text}", color=color, size=12, font_family="Consolas"))
        if len(self.live_log_list.controls) > 100:
            self.live_log_list.controls.pop(0)
        self.page.update()

    def write_auth_log(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_auth_log.controls.append(ft.Text(f"[{ts}] {text}", size=12))
        self.page.update()

    def cb_status(self, text):
        self.lbl_global_status.value = text
        self.write_log(text)
        self.page.update()

    def cb_progress_overall(self, frac, done, total):
        self.pb_main.value = frac
        self.lbl_progress.value = t("overall_progress", done, total)
        self.page.update()

    def cb_error(self, text):
        self.lbl_global_status.value = f"❌ {text}"
        self.lbl_global_status.color = ft.colors.RED_400
        self.page.snack_bar = ft.SnackBar(ft.Text(t("error_flet", text)), bgcolor=ft.colors.RED_800)
        self.page.snack_bar.open = True
        self.write_log(f'[ERROR] {text}', ft.colors.RED_400)
        self.page.update()

    def cb_log(self, entry):
        ts = datetime.now().strftime("%H:%M:%S")
        if isinstance(entry, dict):
            msg = entry.get("msg", str(entry))
            level = entry.get("level", "INFO")
            msg_type = entry.get("type", "")
            
            if msg_type == "bot_send":
                color = ft.colors.GREEN_400
                self.write_log(f"✅ {msg}", color)
            else:
                color = ft.colors.RED_400 if level == "WARN" or level == "ERROR" else ft.colors.GREY_300
                self.write_log(msg, color)
        else:
            self.write_log(str(entry))

    def cb_qr(self, url):
        import qrcode
        qr = qrcode.make(url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        self.img_qr.src_base64 = b64
        self.img_qr.visible = True
        self.write_auth_log(t("scan_qr_flet"))
        self.page.update()

    def cb_complete(self, dummy=None):
        self.cb_status(t("waiting"))
        self.btn_pause.text = t("btn_pause")
        self.btn_pause.icon = ft.icons.PAUSE
        self.page.update()

    def cb_stats(self, stats: CopierStats):
        sl = self.stat_labels
        sl["total_msgs"].value = str(stats.total_channel_msgs)
        sl["processed"].value = str(stats.processed_msgs)
        sl["topics"].value = str(stats.copied_topics)
        sl["copied_msgs"].value = str(stats.copied_messages)
        
        elapsed = time.time() - stats.start_time if stats.start_time else 0
        sl["elapsed"].value = format_duration(elapsed)
        
        sl["eta"].value = format_duration(stats.eta_seconds)
        self.page.update()

    async def cb_request_input(self, title, prompt):
        future = asyncio.get_running_loop().create_future()
        
        def on_submit(e):
            val = inp.value
            dlg.open = False
            self.page.update()
            future.set_result(val)

        inp = ft.TextField(label=prompt, autofocus=True, on_submit=on_submit)
        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=inp,
            actions=[ft.TextButton(t("btn_ok"), on_click=on_submit)]
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
        
        return await future

    async def on_auth_reader(self, e):
        self.on_save_settings(None)
        self.write_auth_log(t("checking_reader"))
        self.img_qr.visible = False
        self.page.update()
        try:
            ok = await self.copier.authorize_client(self.copier.reader, "reader_phone", "Reader")
            if ok:
                self.write_auth_log(t("reader_auth_ok"))
            else:
                self.write_auth_log(t("reader_auth_fail"))
        except Exception as err:
            self.write_auth_log(t("error_flet", str(err)))
        await self.check_auth_on_startup()
        
    async def on_auth_creator(self, e):
        self.on_save_settings(None)
        self.write_auth_log(t("checking_creator"))
        self.img_qr.visible = False
        self.page.update()
        try:
            ok = await self.copier.authorize_client(self.copier.creator, "creator_phone", "Creator")
            if ok:
                self.write_auth_log(t("creator_auth_ok"))
            else:
                self.write_auth_log(t("creator_auth_fail"))
        except Exception as err:
            self.write_auth_log(t("error_flet", str(err)))
        await self.check_auth_on_startup()

    async def on_auth_bot(self, e):
        self.on_save_settings(None)
        self.write_auth_log(t("checking_bot"))
        self.img_qr.visible = False
        self.page.update()
        try:
            ok = await self.copier.authorize_bot()
            if ok:
                self.write_auth_log(t("bot_auth_ok"))
            else:
                self.write_auth_log(t("bot_auth_fail"))
        except Exception as err:
            self.write_auth_log(t("error_flet", str(err)))
        await self.check_auth_on_startup()

    async def on_logout(self, e):
        await self.copier.disconnect()
        try:
            for s in ["session_reader.session", "session_reader.session-journal",
                      "session_creator.session", "session_creator.session-journal",
                      "session_bot.session", "session_bot.session-journal"]:
                if os.path.exists(s):
                    os.remove(s)
            self.write_auth_log(t("sessions_deleted"))
        except Exception as ex:
            self.write_auth_log(t("error_flet", str(ex)))
        
        await self.check_auth_on_startup()

    async def on_start_dl(self, e):
        """
        Starts the downloading and copying process asynchronously.
        Saves current settings and launches CopierCore.
        """
        self.on_save_settings(None)
        asyncio.create_task(self.copier.start_copy())

    def on_pause(self, e):
        if not self.copier.is_running:
            return
        is_paused = self.copier.toggle_pause()
        if is_paused:
            self.btn_pause.text = t("btn_resume")
            self.btn_pause.icon = ft.icons.PLAY_ARROW
            self.btn_pause.color = ft.colors.GREEN_400
        else:
            self.btn_pause.text = t("btn_pause")
            self.btn_pause.icon = ft.icons.PAUSE
            self.btn_pause.color = ft.colors.ORANGE_400
        self.page.update()

    async def on_stop_dl(self, e):
        await self.copier.stop()

    async def on_reset(self, e):
        def do_reset(ev):
            dlg.open = False
            self.page.update()
            cfg = self.copier.config
            if "copied_channels" in cfg:
                cfg["copied_channels"] = {}
            save_config(cfg)
            self.write_log(t("cache_reset_success"), ft.colors.ORANGE_400)
            
        dlg = ft.AlertDialog(
            title=ft.Text(t("reset_cache_title")),
            content=ft.Text(t("reset_cache_desc")),
            actions=[
                ft.TextButton(t("cancel"), on_click=lambda e: setattr(dlg, 'open', False) or self.page.update()),
                ft.TextButton(t("reset"), on_click=do_reset, style=ft.ButtonStyle(color=ft.colors.RED_400))
            ]
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

async def main(page: ft.Page):
    app = TelegramCopierFlet(page)

if __name__ == "__main__":
    ft.app(target=main)
