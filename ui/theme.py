from kivy.event import EventDispatcher
from kivy.properties import ListProperty, StringProperty
from core.config import ConfigManager

class Theme(EventDispatcher):
    current = StringProperty("dark")
    bg_color = ListProperty([0.04, 0.06, 0.10, 1.0])
    card_bg = ListProperty([1.0, 1.0, 1.0, 0.06])
    card_border = ListProperty([1.0, 1.0, 1.0, 0.14])
    input_bg = ListProperty([0.12, 0.15, 0.22, 0.75])
    input_border = ListProperty([1.0, 1.0, 1.0, 0.18])
    text_primary = ListProperty([0.98, 0.98, 1.0, 1.0])
    text_secondary = ListProperty([0.62, 0.68, 0.78, 1.0])
    accent_yellow = ListProperty([1.0, 0.80, 0.02, 1.0])
    accent_orange = ListProperty([1.0, 0.42, 0.05, 1.0])
    accent_blue = ListProperty([0.20, 0.68, 1.0, 1.0])
    accent_green = ListProperty([0.18, 0.85, 0.48, 1.0])
    danger_red = ListProperty([1.0, 0.28, 0.28, 1.0])
    progress_bg = ListProperty([1.0, 1.0, 1.0, 0.08])
    modal_bg = ListProperty([0.05, 0.07, 0.12, 0.92])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cfg_theme = ConfigManager.get_instance().theme
        self.set_theme(cfg_theme, save=False)

    def set_theme(self, theme_name: str, save: bool = True):
        self.current = theme_name
        if save:
            ConfigManager.get_instance().theme = theme_name

        if theme_name == "dark":
            self.bg_color = [0.04, 0.06, 0.10, 1.0]
            self.card_bg = [1.0, 1.0, 1.0, 0.065]
            self.card_border = [1.0, 1.0, 1.0, 0.15]
            self.input_bg = [0.10, 0.14, 0.22, 0.80]
            self.input_border = [1.0, 1.0, 1.0, 0.18]
            self.text_primary = [0.98, 0.98, 1.0, 1.0]
            self.text_secondary = [0.65, 0.70, 0.80, 1.0]
            self.accent_yellow = [1.0, 0.80, 0.02, 1.0]
            self.accent_orange = [1.0, 0.42, 0.05, 1.0]
            self.accent_blue = [0.20, 0.68, 1.0, 1.0]
            self.accent_green = [0.18, 0.85, 0.48, 1.0]
            self.danger_red = [1.0, 0.28, 0.28, 1.0]
            self.progress_bg = [1.0, 1.0, 1.0, 0.08]
            self.modal_bg = [0.05, 0.07, 0.12, 0.94]
        else:
            # Light theme (frosted glass)
            self.bg_color = [0.93, 0.95, 0.98, 1.0]
            self.card_bg = [1.0, 1.0, 1.0, 0.85]
            self.card_border = [0.0, 0.0, 0.0, 0.08]
            self.input_bg = [0.88, 0.91, 0.96, 0.95]
            self.input_border = [0.0, 0.0, 0.0, 0.12]
            self.text_primary = [0.08, 0.10, 0.16, 1.0]
            self.text_secondary = [0.38, 0.44, 0.54, 1.0]
            self.accent_yellow = [0.95, 0.72, 0.00, 1.0]
            self.accent_orange = [0.95, 0.38, 0.00, 1.0]
            self.accent_blue = [0.08, 0.52, 0.92, 1.0]
            self.accent_green = [0.10, 0.70, 0.35, 1.0]
            self.danger_red = [0.90, 0.20, 0.20, 1.0]
            self.progress_bg = [0.0, 0.0, 0.0, 0.08]
            self.modal_bg = [0.96, 0.97, 0.99, 0.96]

    def toggle(self):
        new_theme = "light" if self.current == "dark" else "dark"
        self.set_theme(new_theme, save=True)

theme = Theme()
