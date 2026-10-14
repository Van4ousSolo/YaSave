import webbrowser
import threading
from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.clock import mainthread, Clock
from kivy.core.clipboard import Clipboard
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, RoundedRectangle, Line

from ui.theme import theme
from ui.components import GlassCard, GlassButton, GlassTextInput
from core.auth import AuthManager
from core.config import ConfigManager
from core.alt_sources import AlternativeSourcesManager

class GlassModalView(ModalView):
    def __init__(self, **kwargs):
        kwargs['background_color'] = (0, 0, 0, 0.65)
        super().__init__(**kwargs)


class TokenModal(GlassModalView):
    def __init__(self, on_token_saved=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, None)
        self.height = 480
        self.auto_dismiss = False
        self.on_token_saved = on_token_saved
        self.auth_mgr = AuthManager()
        self.device_code_data = None
        self.mode = "device"  # "device" or "manual"

        # Main Card container
        self.card = GlassCard(orientation='vertical', padding=22, spacing=14, radius=[22])

        # Header Title
        self.lbl_title = Label(
            text="Авторизация Яндекс Музыки",
            font_size=20,
            bold=True,
            color=theme.text_primary,
            size_hint_y=None,
            height=30
        )

        # Tab Switch Buttons
        self.tabs_box = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)
        self.btn_tab_device = GlassButton(text="Автоматически (Код)", variant="primary", font_size=13)
        self.btn_tab_manual = GlassButton(text="Вручную (Токен)", variant="glass", font_size=13)
        self.btn_tab_device.bind(on_release=lambda x: self.switch_mode("device"))
        self.btn_tab_manual.bind(on_release=lambda x: self.switch_mode("manual"))
        self.tabs_box.add_widget(self.btn_tab_device)
        self.tabs_box.add_widget(self.btn_tab_manual)

        # Content container
        self.content_area = BoxLayout(orientation='vertical', spacing=12)

        # === DEVICE MODE WIDGETS ===
        self.device_box = BoxLayout(orientation='vertical', spacing=10)
        self.lbl_device_desc = Label(
            text="1. Перейдите на ya.ru/device\n2. Введите указанный ниже код:",
            font_size=14,
            color=theme.text_secondary,
            halign='center',
            size_hint_y=None,
            height=44
        )
        self.lbl_user_code = Label(
            text="Получение кода...",
            font_size=28,
            bold=True,
            color=theme.accent_yellow,
            halign='center',
            size_hint_y=None,
            height=50
        )
        
        self.device_actions = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)
        self.btn_open_browser = GlassButton(text="Открыть ya.ru/device", variant="glass", font_size=13)
        self.btn_open_browser.bind(on_release=self.open_browser_link)
        self.btn_copy_code = GlassButton(text="Скопировать код", variant="glass", font_size=13)
        self.btn_copy_code.bind(on_release=self.copy_user_code)
        self.device_actions.add_widget(self.btn_open_browser)
        self.device_actions.add_widget(self.btn_copy_code)

        self.lbl_poll_status = Label(
            text="Ожидание подтверждения в браузере...",
            font_size=13,
            color=theme.text_secondary,
            halign='center',
            size_hint_y=None,
            height=25
        )

        self.device_box.add_widget(self.lbl_device_desc)
        self.device_box.add_widget(self.lbl_user_code)
        self.device_box.add_widget(self.device_actions)
        self.device_box.add_widget(self.lbl_poll_status)

        # === MANUAL MODE WIDGETS ===
        self.manual_box = BoxLayout(orientation='vertical', spacing=10)
        self.lbl_manual_desc = Label(
            text="Вставьте ваш OAuth токен Яндекс Музыки:",
            font_size=14,
            color=theme.text_secondary,
            size_hint_y=None,
            height=25
        )
        self.token_input = GlassTextInput(
            hint_text="y0_AgAAAA... или AQAAAA...",
            size_hint_y=None,
            height=50,
            font_size=14,
            multiline=False
        )
        self.btn_save_token = GlassButton(
            text="Проверить и сохранить",
            variant="primary",
            size_hint_y=None,
            height=44,
            font_size=14
        )
        self.btn_save_token.bind(on_release=self.save_manual_token)
        self.lbl_manual_status = Label(
            text="",
            font_size=13,
            color=theme.text_secondary,
            size_hint_y=None,
            height=25
        )
        self.manual_box.add_widget(self.lbl_manual_desc)
        self.manual_box.add_widget(self.token_input)
        self.manual_box.add_widget(self.btn_save_token)
        self.manual_box.add_widget(self.lbl_manual_status)

        # Bottom Close / Skip button
        self.btn_cancel = GlassButton(
            text="Закрыть",
            variant="glass",
            size_hint_y=None,
            height=40,
            font_size=13
        )
        self.btn_cancel.bind(on_release=self.dismiss_modal)

        self.card.add_widget(self.lbl_title)
        self.card.add_widget(self.tabs_box)
        self.card.add_widget(self.content_area)
        self.card.add_widget(self.btn_cancel)
        self.add_widget(self.card)

        # Start in device mode
        self.switch_mode("device")

    def switch_mode(self, mode: str):
        self.mode = mode
        self.content_area.clear_widgets()
        if mode == "device":
            self.btn_tab_device.variant = "primary"
            self.btn_tab_manual.variant = "glass"
            self.content_area.add_widget(self.device_box)
            self.request_device_code()
        else:
            self.btn_tab_device.variant = "glass"
            self.btn_tab_manual.variant = "primary"
            self.content_area.add_widget(self.manual_box)
            self.auth_mgr.stop_device_polling()

    def request_device_code(self):
        self.lbl_user_code.text = "Генерация кода..."
        def task():
            try:
                data = self.auth_mgr.request_device_flow()
                self.on_device_code_received(data)
            except Exception as e:
                self.on_device_error(f"Ошибка запроса: {e}")
        threading.Thread(target=task, daemon=True).start()

    @mainthread
    def on_device_code_received(self, data: dict):
        self.device_code_data = data
        code = data.get("user_code", "---")
        self.lbl_user_code.text = code
        self.lbl_poll_status.text = "Ожидание подтверждения..."
        self.lbl_poll_status.color = theme.accent_yellow

        self.auth_mgr.start_device_polling(
            device_code=data["device_code"],
            interval=data.get("interval", 5),
            on_success=self.on_auth_success,
            on_error=self.on_device_error
        )

    @mainthread
    def on_auth_success(self, token: str):
        self.lbl_poll_status.text = "Успешная авторизация!"
        self.lbl_poll_status.color = theme.accent_green
        Clock.schedule_once(lambda dt: self._finish(token), 1.0)

    @mainthread
    def on_device_error(self, err_msg: str):
        self.lbl_poll_status.text = err_msg
        self.lbl_poll_status.color = theme.danger_red

    def open_browser_link(self, *args):
        url = "https://ya.ru/device"
        if self.device_code_data:
            url = self.device_code_data.get("verification_url", url)
        webbrowser.open(url)

    def copy_user_code(self, *args):
        if self.device_code_data and "user_code" in self.device_code_data:
            Clipboard.copy(self.device_code_data["user_code"])
            self.lbl_poll_status.text = "Код скопирован в буфер обмена!"

    def save_manual_token(self, *args):
        tok = self.token_input.text.strip()
        if not tok:
            self.lbl_manual_status.text = "Введите токен!"
            self.lbl_manual_status.color = theme.danger_red
            return
        
        self.btn_save_token.disabled = True
        self.lbl_manual_status.text = "Проверка токена..."
        self.lbl_manual_status.color = theme.accent_yellow

        def task():
            is_valid, msg = self.auth_mgr.validate_token(tok)
            self._on_manual_result(is_valid, msg, tok)
        threading.Thread(target=task, daemon=True).start()

    @mainthread
    def _on_manual_result(self, is_valid: bool, msg: str, tok: str):
        self.btn_save_token.disabled = False
        if is_valid:
            self.lbl_manual_status.text = f"Успешно: {msg}"
            self.lbl_manual_status.color = theme.accent_green
            ConfigManager.get_instance().token = tok
            Clock.schedule_once(lambda dt: self._finish(tok), 0.8)
        else:
            self.lbl_manual_status.text = msg
            self.lbl_manual_status.color = theme.danger_red

    def _finish(self, token: str):
        self.dismiss()
        if self.on_token_saved:
            self.on_token_saved(token)

    def dismiss_modal(self, *args):
        self.auth_mgr.stop_device_polling()
        self.dismiss()


class AlternativeSourcesModal(GlassModalView):
    def __init__(self, ym_track_info: dict, on_select_download=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.94, 0.85)
        self.ym_track_info = ym_track_info
        self.on_select_download = on_select_download
        self.current_sound = None
        self.playing_candidate_id = None

        self.card = GlassCard(orientation='vertical', padding=18, spacing=12, radius=[20])

        # Header
        self.header = BoxLayout(orientation='vertical', size_hint_y=None, height=54, spacing=4)
        self.lbl_title = Label(
            text="Поиск трека без цензуры",
            font_size=18,
            bold=True,
            color=theme.text_primary,
            size_hint_y=None,
            height=26
        )
        self.lbl_subtitle = Label(
            text=f"{ym_track_info.get('artist')} - {ym_track_info.get('title')}",
            font_size=13,
            color=theme.accent_yellow,
            size_hint_y=None,
            height=22,
            shorten=True
        )
        self.header.add_widget(self.lbl_title)
        self.header.add_widget(self.lbl_subtitle)

        # Status / Spinner
        self.lbl_status = Label(
            text="Ищем варианты в YouTube / SoundCloud...",
            font_size=13,
            color=theme.text_secondary,
            size_hint_y=None,
            height=24
        )

        # Scrollable candidates list
        self.scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.list_layout = GridLayout(cols=1, spacing=10, size_hint_y=None)
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        self.scroll.add_widget(self.list_layout)

        # Bottom Close Button
        self.btn_close = GlassButton(
            text="Закрыть",
            variant="glass",
            size_hint_y=None,
            height=42,
            font_size=14
        )
        self.btn_close.bind(on_release=self.on_close_modal)

        self.card.add_widget(self.header)
        self.card.add_widget(self.lbl_status)
        self.card.add_widget(self.scroll)
        self.card.add_widget(self.btn_close)
        self.add_widget(self.card)

        # Trigger search in background
        self.load_candidates()

    def load_candidates(self):
        def task():
            candidates = AlternativeSourcesManager.search_candidates(
                artist=self.ym_track_info.get("artist", ""),
                title=self.ym_track_info.get("title", ""),
                limit=6
            )
            self.on_candidates_loaded(candidates)
        threading.Thread(target=task, daemon=True).start()

    @mainthread
    def on_candidates_loaded(self, candidates: list):
        self.list_layout.clear_widgets()
        if not candidates:
            self.lbl_status.text = "Варианты не найдены. Попробуйте другой запрос."
            self.lbl_status.color = theme.danger_red
            return

        self.lbl_status.text = f"Найдено вариантов: {len(candidates)}. Выберите подходящий:"
        self.lbl_status.color = theme.accent_green

        for item in candidates:
            row = GlassCard(orientation='vertical', padding=12, spacing=8, size_hint_y=None, height=115, radius=[14])
            
            # Row header: Title + Duration
            top = BoxLayout(orientation='horizontal', size_hint_y=None, height=24)
            lbl_item_title = Label(
                text=item["title"],
                font_size=14,
                bold=True,
                color=theme.text_primary,
                halign='left',
                shorten=True,
                size_hint_x=0.8
            )
            lbl_item_title.bind(size=lbl_item_title.setter('text_size'))
            
            lbl_dur = Label(
                text=item["duration_str"],
                font_size=12,
                color=theme.text_secondary,
                size_hint_x=0.2,
                halign='right'
            )
            top.add_widget(lbl_item_title)
            top.add_widget(lbl_dur)

            # Middle: Channel / Source
            lbl_meta = Label(
                text=f"{item['channel']} • {item['source']}",
                font_size=12,
                color=theme.text_secondary,
                size_hint_y=None,
                height=18,
                halign='left'
            )
            lbl_meta.bind(size=lbl_meta.setter('text_size'))

            # Actions: Preview & Download
            actions = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=36)
            
            btn_play = GlassButton(
                text="▶ Предпросмотр",
                variant="glass",
                font_size=12,
                size_hint_x=0.45
            )
            btn_play.bind(on_release=lambda x, it=item, b=btn_play: self.toggle_preview(it, b))

            btn_dl = GlassButton(
                text="⚡ Скачать этот вариант",
                variant="primary",
                font_size=12,
                size_hint_x=0.55
            )
            btn_dl.bind(on_release=lambda x, it=item: self.select_candidate(it))

            actions.add_widget(btn_play)
            actions.add_widget(btn_dl)

            row.add_widget(top)
            row.add_widget(lbl_meta)
            row.add_widget(actions)
            self.list_layout.add_widget(row)

    def toggle_preview(self, item: dict, btn_widget: GlassButton):
        if self.playing_candidate_id == item["id"] and self.current_sound:
            self.stop_current_sound()
            btn_widget.text = "▶ Предпросмотр"
            return

        self.stop_current_sound()
        btn_widget.text = "Загрузка аудио..."

        def task():
            audio_url = AlternativeSourcesManager.get_preview_audio_url(item["url"])
            if audio_url:
                self._play_stream(audio_url, item["id"], btn_widget)
            else:
                self._on_play_failed(btn_widget)
        threading.Thread(target=task, daemon=True).start()

    @mainthread
    def _play_stream(self, stream_url: str, item_id: str, btn_widget: GlassButton):
        try:
            self.current_sound = SoundLoader.load(stream_url)
            if self.current_sound:
                self.current_sound.play()
                self.playing_candidate_id = item_id
                btn_widget.text = "⏸ Стоп"
                return
        except Exception:
            pass
        self._on_play_failed(btn_widget)

    @mainthread
    def _on_play_failed(self, btn_widget: GlassButton):
        btn_widget.text = "Не удалось воспроизвести"

    def stop_current_sound(self):
        if self.current_sound:
            try:
                self.current_sound.stop()
                self.current_sound.unload()
            except Exception:
                pass
            self.current_sound = None
        self.playing_candidate_id = None

    def select_candidate(self, item: dict):
        self.stop_current_sound()
        self.dismiss()
        if self.on_select_download:
            self.on_select_download(item)

    def on_close_modal(self, *args):
        self.stop_current_sound()
        self.dismiss()
