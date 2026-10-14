import os
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.image import AsyncImage, Image
from kivy.graphics import Color, RoundedRectangle, Line, Rectangle
from kivy.properties import (
    ListProperty,
    NumericProperty,
    StringProperty,
    BooleanProperty,
    ObjectProperty
)
from kivy.animation import Animation
from kivy.clock import Clock
from ui.theme import theme

class GlassCard(BoxLayout):
    radius = ListProperty([18])
    border_width = NumericProperty(1.2)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._update_canvas, size=self._update_canvas)
        theme.bind(card_bg=self._update_canvas, card_border=self._update_canvas)
        self._update_canvas()

    def _update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Translucent frosted fill
            Color(*theme.card_bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
            # Specular glass edge highlight
            Color(*theme.card_border)
            Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius[0]),
                width=self.border_width
            )


class GlassButton(Button):
    radius = ListProperty([14])
    variant = StringProperty("glass")  # "primary", "glass", "secondary", "danger", "accent"
    is_pressed = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bind(pos=self._update_canvas, size=self._update_canvas, state=self._on_state)
        theme.bind(
            accent_yellow=self._update_canvas,
            card_border=self._update_canvas,
            text_primary=self._update_canvas
        )
        self._update_canvas()

    def _on_state(self, instance, value):
        self.is_pressed = (value == 'down')
        self._update_canvas()

    def _update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self.variant == "primary":
                if self.is_pressed:
                    Color(*theme.accent_orange)
                else:
                    Color(*theme.accent_yellow)
                RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
                self.color = (0.05, 0.05, 0.05, 1.0)
            elif self.variant == "danger":
                if self.is_pressed:
                    Color(0.8, 0.2, 0.2, 0.9)
                else:
                    Color(*theme.danger_red)
                RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
                self.color = (1.0, 1.0, 1.0, 1.0)
            elif self.variant == "accent":
                if self.is_pressed:
                    Color(0.1, 0.5, 0.8, 0.9)
                else:
                    Color(*theme.accent_blue)
                RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
                self.color = (1.0, 1.0, 1.0, 1.0)
            else:  # "glass" or "secondary"
                if self.is_pressed:
                    Color(1.0, 1.0, 1.0, 0.25 if theme.current == "dark" else 0.7)
                else:
                    Color(*theme.card_bg)
                RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
                Color(*theme.card_border)
                Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius[0]),
                    width=1.2
                )
                self.color = theme.text_primary


class GlassTextInput(TextInput):
    radius = ListProperty([14])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_active = ''
        self.background_color = (0, 0, 0, 0)
        self.padding = [16, 14, 16, 14]
        self.cursor_color = theme.accent_yellow
        self.bind(pos=self._update_canvas, size=self._update_canvas, focus=self._update_canvas)
        theme.bind(
            input_bg=self._update_canvas,
            input_border=self._update_canvas,
            text_primary=self._update_canvas,
            accent_yellow=self._update_canvas
        )
        self._update_canvas()

    def _update_canvas(self, *args):
        self.foreground_color = theme.text_primary
        self.cursor_color = theme.accent_yellow
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*theme.input_bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
            if self.focus:
                Color(*theme.accent_yellow)
                Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius[0]),
                    width=1.8
                )
            else:
                Color(*theme.input_border)
                Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius[0]),
                    width=1.0
                )


class GlassProgressBar(BoxLayout):
    progress = NumericProperty(0.0)  # 0.0 to 100.0
    radius = ListProperty([10])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = 36
        self.spacing = 6

        # Header with percentage and status
        self.info_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=20)
        self.lbl_status = Label(
            text="0%",
            font_size=13,
            bold=True,
            halign='left',
            valign='middle',
            color=theme.accent_yellow,
            size_hint_x=0.4
        )
        self.lbl_status.bind(size=self.lbl_status.setter('text_size'))

        self.lbl_details = Label(
            text="",
            font_size=12,
            halign='right',
            valign='middle',
            color=theme.text_secondary,
            size_hint_x=0.6
        )
        self.lbl_details.bind(size=self.lbl_details.setter('text_size'))

        self.info_box.add_widget(self.lbl_status)
        self.info_box.add_widget(self.lbl_details)

        # Track bar container
        self.track_widget = Widget(size_hint=(1, None), height=10)
        self.track_widget.bind(pos=self._update_track, size=self._update_track)
        self.bind(progress=self._update_track)
        theme.bind(
            progress_bg=self._update_track,
            accent_yellow=self._update_track,
            text_secondary=self._update_track
        )

        self.add_widget(self.info_box)
        self.add_widget(self.track_widget)

    def set_progress(self, percent: float, downloaded_mb: float = 0.0, total_mb: float = 0.0, speed_str: str = ""):
        self.progress = max(0.0, min(100.0, percent))
        self.lbl_status.text = f"{self.progress:.1f}%"
        self.lbl_status.color = theme.accent_yellow

        if total_mb > 0:
            speed_part = f" • {speed_str}" if speed_str else ""
            self.lbl_details.text = f"{downloaded_mb:.1f} / {total_mb:.1f} МБ{speed_part}"
        elif speed_str:
            self.lbl_details.text = speed_str
        else:
            self.lbl_details.text = ""
        self.lbl_details.color = theme.text_secondary
        self._update_track()

    def _update_track(self, *args):
        self.track_widget.canvas.before.clear()
        with self.track_widget.canvas.before:
            # Background track
            Color(*theme.progress_bg)
            RoundedRectangle(
                pos=self.track_widget.pos,
                size=self.track_widget.size,
                radius=self.radius
            )
            # Active fill
            fill_width = max(6.0, (self.progress / 100.0) * self.track_widget.width) if self.progress > 0 else 0
            if fill_width > 0:
                Color(*theme.accent_yellow)
                RoundedRectangle(
                    pos=self.track_widget.pos,
                    size=(fill_width, self.track_widget.height),
                    radius=self.radius
                )


class TrackPreviewCard(GlassCard):
    def __init__(self, **kwargs):
        kwargs['orientation'] = 'horizontal'
        kwargs['padding'] = 14
        kwargs['spacing'] = 14
        kwargs['size_hint_y'] = None
        kwargs['height'] = 120
        super().__init__(**kwargs)

        # Cover image with fallback
        self.cover_image = AsyncImage(
            source='assets/cover.jpg' if os.path.exists('assets/cover.jpg') else '',
            size_hint=(None, None),
            size=(92, 92),
            allow_stretch=True,
            keep_ratio=False
        )

        # Track metadata column
        self.info_col = BoxLayout(orientation='vertical', spacing=4)
        
        self.lbl_title = Label(
            text="Выберите или вставьте трек",
            font_size=17,
            bold=True,
            color=theme.text_primary,
            halign='left',
            valign='middle',
            shorten=True,
            shorten_from='right',
            size_hint_y=0.4
        )
        self.lbl_title.bind(size=self.lbl_title.setter('text_size'))

        self.lbl_artist = Label(
            text="Исполнитель появится здесь",
            font_size=14,
            color=theme.text_secondary,
            halign='left',
            valign='middle',
            shorten=True,
            shorten_from='right',
            size_hint_y=0.3
        )
        self.lbl_artist.bind(size=self.lbl_artist.setter('text_size'))

        # Badges row
        self.badges_row = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=0.3)
        self.lbl_duration = Label(
            text="--:--",
            font_size=12,
            color=theme.text_secondary,
            size_hint_x=None,
            width=50,
            halign='left'
        )
        self.lbl_bitrate = Label(
            text="320 kbps MP3",
            font_size=12,
            color=theme.accent_yellow,
            size_hint_x=None,
            width=90,
            halign='left'
        )
        self.lbl_explicit = Label(
            text="18+ EXPLICIT",
            font_size=11,
            bold=True,
            color=theme.danger_red,
            size_hint_x=None,
            width=80,
            opacity=0.0
        )

        self.badges_row.add_widget(self.lbl_duration)
        self.badges_row.add_widget(self.lbl_bitrate)
        self.badges_row.add_widget(self.lbl_explicit)

        self.info_col.add_widget(self.lbl_title)
        self.info_col.add_widget(self.lbl_artist)
        self.info_col.add_widget(self.badges_row)

        self.add_widget(self.cover_image)
        self.add_widget(self.info_col)

        theme.bind(
            text_primary=self._sync_theme,
            text_secondary=self._sync_theme,
            accent_yellow=self._sync_theme
        )

    def _sync_theme(self, *args):
        self.lbl_title.color = theme.text_primary
        self.lbl_artist.color = theme.text_secondary
        self.lbl_duration.color = theme.text_secondary
        self.lbl_bitrate.color = theme.accent_yellow

    def update_track(self, track_info: dict):
        self.lbl_title.text = track_info.get("title", "Неизвестный трек")
        self.lbl_artist.text = track_info.get("artist", "Неизвестный исполнитель")
        self.lbl_duration.text = track_info.get("duration_str", "--:--")
        
        if track_info.get("explicit"):
            self.lbl_explicit.opacity = 1.0
        else:
            self.lbl_explicit.opacity = 0.0

        cover_url = track_info.get("cover_url")
        if cover_url:
            self.cover_image.source = cover_url
        elif os.path.exists('assets/cover.jpg'):
            self.cover_image.source = 'assets/cover.jpg'
