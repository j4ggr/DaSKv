import math
import textwrap

from typing import Any
from typing import Self
from typing import List
from typing import Dict
from typing import Tuple
from typing import Literal
from pathlib import Path
from numpy.typing import ArrayLike

from matplotlib.pyplot import tight_layout
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox
from matplotlib.backend_bases import _Mode
from matplotlib.backend_bases import MouseEvent
from matplotlib.backend_bases import MouseButton
from matplotlib.backends.backend_agg import RendererAgg

from kivy.lang import Builder
from kivy.base import EventLoop
from kivy.metrics import sp
from kivy.metrics import dp
from kivy.animation import Animation
from kivy.uix.widget import Widget
from kivy.properties import ListProperty
from kivy.properties import ObjectProperty
from kivy.properties import StringProperty
from kivy.properties import NumericProperty
from kivy.properties import BooleanProperty
from kivy.uix.gridlayout import GridLayout
from kivy.graphics.texture import Texture
from kivy.input.motionevent import MotionEvent
from kivy.uix.relativelayout import RelativeLayout
from kivy.core.window.window_sdl2 import WindowSDL

from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton

from .backend_kivy import Navigation
from .backend_kivy import FigureCanvas


class MatplotFigure(Widget):
    """Kivy Widget to show a matplotlib figure in kivy.
    The figure is rendered internally in an AGG backend then
    the rgb data is obtained and blitted into a kivy texture.
    
    Parameters
    ----------
    figure : `~matplotlib.figure.Figure`
        The top level container for all the plot elements.
    """
    figure: Figure = ObjectProperty(None)
    """The matplotlib figure object as the top level container for all 
    the plot elements. If this property changes, a new FigureCanvas is
    created, see method `on_figure` (callback)."""
    
    figure_canvas: FigureCanvas = ObjectProperty(None)
    """Canvas to render the plots into. Is set in method `on_figure` (callback)."""
    
    texture: Texture = ObjectProperty(None)
    """Texture to blit the figure into."""

    rubberband_pos: List[float] = ListProperty([0, 0])
    """Position of rubberband when using the zoom tool."""
    
    rubberband_size: List[float] = ListProperty([0, 0])
    """Current size of rubberband when using the zoom tool."""
    
    rubberband_corners: List[float] = ListProperty([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    """Current corner positions of rubberband when using the zoom tool."""
    
    rubberband_threshold: float = dp(20)
    """Threshold at which it will switch between axis-wise zoom or 
    rectangle zoom"""
    
    toolbar: Any = ObjectProperty(None)
    """Toolbar widget to display the toolbar."""
    
    is_pressed: bool = False
    """Flag to distinguish whether the mouse is moved with the key pressed or not"""
    
    mouse_pos: List[float] = ListProperty([0, 0])
    """Current mouse position"""
    
    inaxes: Axes | None = None
    """Current axis on which the mouse is hovering, is automatically 
    set in `on_mouse_pos` callback"""

    show_info: bool = BooleanProperty(False)
    """Flag to show the info label"""

    def __init__(self, *args, **kwargs) -> None:
        Builder.load_string(textwrap.dedent(f"""
            <{self.__class__.__name__}>:
                # background
                canvas.before:
                    Color:
                        rgba: (1, 1, 1, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                        texture: self.texture
                # rubberband area
                canvas:
                    Color:
                        rgba: (0, 0, 0, 0.2)
                    BorderImage:
                        source: 'border.png'
                        pos: self.rubberband_pos
                        size: self.rubberband_size
                        border: (1, 1, 1, 1)
                # rubberband edges
                canvas.after: 
                    Color:
                        rgba: (0, 0, 0, 0.6)
                    Line:
                        points: self.rubberband_corners
                        width: 1
                        dash_offset: 4
                        dash_length: 6"""))
        super().__init__(*args, **kwargs)

        EventLoop.window.bind(mouse_pos=self.on_mouse_move) # type: ignore
        self.bind(size=self.on_size) # type: ignore
    
    @property
    def rubberband_drawn(self) -> bool:
        """True if a rubberband is drawn (read-only)"""
        return self.rubberband_size[0] > 1 or self.rubberband_size[1] > 1
    
    def on_mouse_pos(
            self, caller: Self, mouse_pos: Tuple[float, float]) -> None:
        """Callback function, called when `mouse_pos` attribute changes."""
        if self.figure_canvas is None:
            self.inaxes = None
        else:
            self.inaxes = self.figure_canvas.inaxes(mouse_pos)
    
    def on_touch_down(self, touch: MotionEvent) -> None:
        """Callback function, called on mouse button press or touch 
        event."""
        if not self.collide_point(touch.x, touch.y):
            return
        
        if touch.is_mouse_scrolling:
            return
        
        if touch.is_double_tap:
            self.toolbar.navigation.home()
            return
        
        if self.figure_canvas is None:
            return
        
        self.is_pressed = True
        self.figure_canvas.button_press_event(
            x = touch.x,
            y = touch.y - self.pos[1],
            button = self._button_(touch),
            gui_event = touch)
    
    def on_touch_up(self, touch: MotionEvent) -> None:
        """Callback function, called on mouse button release or touch up
        event."""
        # self.reset_rubberband()
        if not self.collide_point(touch.x, touch.y):
            return
        
        if self.figure_canvas is None:
            return
        
        self.is_pressed = False
        self.figure_canvas.button_release_event(
            x = touch.x,
            y = touch.y - self.pos[1],
            button = self._button_(touch),
            gui_event = touch)
    
    def on_mouse_move(
            self, window: WindowSDL, mouse_pos: Tuple[float, float]) -> None:
        """Callback function, called on mouse movement event"""
        self.mouse_pos = [
            mouse_pos[0] - self.parent.x,
            mouse_pos[1] - self.parent.y]
        if self.collide_point(*self.mouse_pos) and not self.is_pressed:
            if self.figure_canvas is None:
                return
            
            self.figure_canvas.motion_notify_event(
                x = self.mouse_pos[0],
                y = self.mouse_pos[1] - self.pos[1],
                gui_event = None)
            self.adjust_toolbar_info_pos()
        else:
            self.clear_toolbar_info()

    def on_touch_move(self, touch: MotionEvent) -> None:
        """Callback function, called on mouse movement event while mouse
        button pressed or touch."""
        if not self.collide_point(touch.x, touch.y):
            return
        
        if self.figure_canvas is None:
            return
        
        self.figure_canvas.motion_notify_event(
            x = touch.x,
            y = touch.y - self.pos[1],
            gui_event = touch)

    def on_figure(self, caller: Self, figure: Figure) -> None:
        """Callback function, called when `figure` attribute changes."""
        # self.figure.set_layout_engine('constrained')
        self.figure_canvas = FigureCanvas(self.figure, figure_widget=self)
        self.width = math.ceil(self.figure.bbox.width)
        self.height = math.ceil(self.figure.bbox.height)
        self.texture = Texture.create(size=(self.width, self.height))

    def on_size(self, caller: Self, size: Tuple[float, float]) -> None:
        """Creat a new, correctly sized bitmap"""
        if self.figure is None or size[0] <= 1 or size[1] <= 1:
            return
        
        self.width, self.height = size
        self.figure.set_size_inches(
            self.width/self.figure.dpi, self.height/self.figure.dpi)
        self.figure_canvas.resize_event()
        self.figure_canvas.draw()
    
    def data_to_axes(self, points: ArrayLike) -> ArrayLike:
        """Transform points from the data coordinate system to the 
        axes coordinate system. Given points should be an array with
        shape (N, 2) or a single point as a tuple containing 2 floats
        """
        if self.inaxes is None:
            return points
        points = (
            self.inaxes.transData
            + self.inaxes.transAxes.inverted()
            ).transform(points)
        return points
    
    def display_to_data(self, points: ArrayLike) -> ArrayLike:
        """Transform points from the display coordinate system to the 
        data coordinate system. Given points should be an array with
        shape (N, 2) or a single point as a tuple containing 2 floats.
        """
        if self.inaxes is None:
            return points
        return self.inaxes.transData.inverted().transform(points)
    
    def data_to_display(self, points: ArrayLike) -> ArrayLike:
        """Transform points from the data coordinate system to the 
        display coordinate system. Given points should be an array with
        shape (N, 2) or a single point as a tuple containing 2 floats.
        """
        if self.inaxes is None:
            return points
        return self.inaxes.transData.transform(points)
    
    def display_to_axes(self, points: ArrayLike) -> ArrayLike:
        """Transform points from the display coordinate system to the 
        data coordinate system. Given points should be an array with
        shape (N, 2) or a single point as a tuple containing 2 floats.
        """
        if self.inaxes is None:
            return points
        return self.inaxes.transAxes.inverted().transform(points)
    
    def draw_rubberband(
            self, touch: MouseEvent, x0: float, y0: float, x1: float, y1: float
            ) -> None:
        """Draw a rectangle rubberband to indicate zoom limits.
    
        Parameters
        ----------
        touch : `~matplotlib.backend_bases.MouseEvent`
            Touch event
        x0 : float
            x coordonnate init
        x1 : float
            y coordonnate of move touch
        y0 : float
            y coordonnate init
        y1 : float
            x coordonnate of move touch"""
        if self.toolbar is not None:
            self.toolbar.navigation.zoom_x_only = False
            self.toolbar.navigation.zoom_y_only = False
            ax = self.toolbar.navigation._zoom_info.axes[0]
            width = abs(x1 - x0)
            height = abs(y1 - y0)
            if width < self.rubberband_threshold < height:
                x0, x1 = ax.bbox.intervalx
                self.toolbar.navigation.zoom_y_only = True
            elif height < self.rubberband_threshold < width:
                y0, y1 = ax.bbox.intervaly
                self.toolbar.navigation.zoom_x_only = True

        if x0 > x1: 
            x0, x1 = x1, x0
        if y0 > y1: 
            y0, y1 = y1, y0
        y0 += self.pos[1]
        y1 += self.pos[1]

        self.rubberband_pos = [x0, y0]
        self.rubberband_size = [x1 - x0, y1 - y0]
        self.rubberband_corners = [x0, y0, x1, y0, x1, y1, x0, y1, x0, y0]
    
    def remove_rubberband(self) -> None:
        """Remove rubberband if is drawn."""
        if not self.rubberband_drawn:
            return
        
        self.rubberband_pos = [0, 0]
        self.rubberband_size = [0, 0]
        self.rubberband_corners = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    def on_show_info(self, caller: Any, show_info: bool) -> None:
        """Callback function, called when `show_info` attribute changes.
        Clear toolbar label if show_info is False."""
        if not show_info:
            self.clear_toolbar_info()
    
    def clear_toolbar_info(self) -> None:
        """Clear text of toolbar label if available"""
        if self.toolbar is None:
            return
        
        self.toolbar.info_label.text = ''
    
    def adjust_toolbar_info_pos(self, *args) -> None:
        """Adjust position of toolbar label if available"""
        if self.toolbar is None or self.toolbar.info_label.text == '':
            return
        self.toolbar.info_label.pos = (
            self.mouse_pos[0] - self.toolbar.info_label.width/2,
            self.mouse_pos[1])

    def _draw_bitmap_(self, renderer: RendererAgg) -> None:
        size = (renderer.width, renderer.height)
        bitmap = renderer.tostring_argb()
        self.texture = Texture.create(size=size)
        self.texture.blit_buffer(bitmap, colorfmt='argb', bufferfmt='ubyte')
        self.texture.flip_vertical()
    
    def _button_(
            self, event: MotionEvent
            ) -> MouseButton | Literal['up', 'down'] | None:
        """If possible, connvert `button` attribute of given event to a
        number using enum `~matplotlib.backend_bases.MouseButton`. If it
        is a scroll event, return "up" or "down" as appropriate."""
        name: str = event.button # type: ignore
        if hasattr(MouseButton, name.upper()):
            button = MouseButton[name.upper()]
        elif 'scroll' in name:
            button = name.replace('scroll', '')
        else:
            button = None
        return button # type: ignore


class InfoLabel(MDLabel):
    """Label used in toolbar to display information."""

    def __init__(self, *args, **kwargs) -> None:
        _kwargs = dict(
            text='',
            theme_text_color='Custom',
            text_color=(0, 0, 0, 0.4),
            font_style='Label',
            role='medium',
            size_hint=(None, None),
            size=(dp(150), dp(20)),
            valign='bottom',
            halign='center',
            ) | kwargs
        super().__init__(*args, **_kwargs)


class ToolbarButton(MDIconButton):

    def __init__(self, *args, **kwargs) -> None:
        _kwargs = dict(
            theme_icon_color='Custom',
            icon_color=(0, 0, 0, 0.4),
            theme_font_size='Custom',
            font_size=sp(18),
            size=(dp(2), dp(2)),
            ) | kwargs
        super().__init__(*args, **_kwargs)
        self.radius = [self.height / 2, ]


class IconToggleButton(ToolbarButton):

    toggle_group: List = ListProperty([])
    """List of toggle buttons that are in the same group."""

    active: bool = BooleanProperty(False)
    """Is the button active."""

    active_color: List = ListProperty([])
    """Color of the button when active."""
    
    inactive_color: List = ListProperty([])
    """Color of the button when inactive."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.active_color = self.theme_cls.primaryColor
        self.inactive_color = self.icon_color

    def on_active(self, caller: Self, active: bool) -> None:
        if active:
            for button in self.toggle_group:
                if button != self:
                    button.active = False
        self.icon_color = self.active_color if active else self.inactive_color

    def on_press(self) -> None:
        self.active = not self.active


class ToolbarMenu(GridLayout):

    caller: ToolbarButton = ObjectProperty(None)
    """ToolbarButton that called the menu."""

    tools: List = ListProperty([])
    """List of toolbar buttons."""

    is_open: bool = BooleanProperty(False)
    """Flag indicating whether the menu is open."""

    open_transition = StringProperty('in_out_back')
    """The type of transition of the widget opening, by default 'linear'."""

    open_duration = NumericProperty(0.1)
    """Duration of widget display transition, by default 0.2."""

    close_transition = StringProperty('in_out_back')
    """The type of transition of the widget closing, by default 'linear'."""

    close_duration = NumericProperty(0.1)
    """Duration of widget closing transition, by default 0.2."""

    is_on_motion = BooleanProperty(False)
    """Flag indicating whether the menu is on motion."""

    def __init__(self, caller: ToolbarButton, *tools, **kwargs) -> None:
        Builder.load_string(textwrap.dedent(f"""
            <{self.__class__.__name__}>:
                cols: 1
                size_hint: (None, None)
                height: 0
                padding: 0
                spacing: 0
                
                # background
                canvas.before:
                    Color:
                        rgba: (0, 0, 0, 0)
                    Rectangle:
                        pos: self.pos
                        size: self.size
                width: self.minimum_width"""))
        self.caller = caller
        self.tools = list(tools)
        super().__init__(**kwargs)
        self.caller.bind(pos=self.adjust_pos)

    @property
    def open_height(self) -> int:
        """Height of toolbar menu."""
        return 100
        # return sum(t.height for t in self.tools)
    
    def adjust_pos(self, *args) -> None:
        """Adjust position of toolbar menu."""
        self.pos = (
            self.caller.x,
            self.caller.y - self.height)

    def add_widget(self, widget: Any, *args, **kwargs) -> None:
        """Add widget to toolbar menu."""
        if widget not in self.tools:
            self.tools.append(widget)
        return super().add_widget(widget, *args, **kwargs)

    def open(self, *args) -> None:
        """Open menu."""
        if self.is_on_motion:
            return
        
        animation = Animation(
            height=self.open_height,
            duration=self.open_duration,
            transition=self.open_transition,)
        animation.bind(
            on_start=self._on_start_,
            on_progress=self._on_motion_,
            on_complete=self._on_motion_complete_)
        animation.start(self)

    def close(self, *args) -> None:
        """Close menu."""
        if self.is_on_motion:
            return
        
        animation = Animation(
            height=0,
            duration=self.close_duration,
            transition=self.close_transition,)
        animation.bind(
            on_start=self._on_start_,
            on_progress=self._on_motion_,
            on_complete=self._on_motion_complete_)
        animation.start(self)
    
    def _on_start_(self, animation: Animation, widget: Self) -> None:
        """Callback function called when menu is opening or closing."""
        self.is_on_motion = True
    
    def _on_motion_(
            self, animation: Animation, widget: Self, progression: float
            ) -> None:
        """Callback function called when menu is opening and closing."""
        self.y = self.caller.y - self.height
        if self.is_open:
            for idx, tool in enumerate(self.tools[::-1]):
                relative_idx = (idx + 1)/len(self.tools)
                if tool not in self.children:
                    continue

                if relative_idx <= progression:
                    self.remove_widget(tool)

        else:
            for idx, tool in enumerate(self.tools):
                relative_idx = (idx + 1)/len(self.tools)
                if tool in self.children:
                    continue

                if relative_idx <= progression:
                    self.add_widget(tool)

    def _on_motion_complete_(self, animation: Animation, widget: Self) -> None:
        """Callback function called when menu opening or closing is 
        completed."""
        self.is_open = not self.is_open
        self.is_on_motion = False


class Toolbar(ToolbarButton):
    """Toolbar widget.
    
    `on_press` callback functions for toolbar buttons are bound in 
    `_bind_callbacks_` method of `~backend.Navigation` class.
    """
    xy_coordinate: str = StringProperty('')
    """xy coordinate."""
    
    figure_widget: MatplotFigure = ObjectProperty(None)
    """Set in `widget.kv` Chart object"""

    menu: ToolbarMenu = ObjectProperty(None)
    """Menu holds toolbar buttons."""

    def __init__(self, info_label: InfoLabel, **kwargs) -> None:
        self.info_label = info_label

        self.home_button = ToolbarButton(icon='home-outline')
        self.back_button = ToolbarButton(icon='undo-variant')
        self.forward_button = ToolbarButton(icon='redo-variant')
        self.coordinate_button = IconToggleButton( # cursor-default-outline
            icon='map-marker-radius-outline', on_release=self.show_coordinate)
        self.pan_button = IconToggleButton(icon='arrow-all')
        self.zoom_button = IconToggleButton(icon='selection-drag')
        self.save_figure_button = ToolbarButton(icon='content-save-outline')
        self.menu = ToolbarMenu(
            self,
            self.home_button,
            self.back_button,
            self.forward_button,
            self.coordinate_button,
            self.pan_button,
            self.zoom_button,
            self.save_figure_button,)

        toggle_group = [
            self.coordinate_button,
            self.pan_button,
            self.zoom_button]
        for button in toggle_group:
            button.toggle_group = toggle_group
        _kwargs = dict(
            icon='menu',
            on_release=self.open_close_menu,
            pos_hint = {'right': 1, 'top': 1},
            ) | kwargs
        super().__init__(**_kwargs)
        self.height = self.home_button.height

    def open_close_menu(self, *args) -> None:
        """Open or close menu."""
        if self.menu.is_open:
            self.menu.close()
        else:
            self.menu.open()

    def on_figure_widget(
            self, caller: Self, figure_widget: MatplotFigure) -> None:
        """Bind `figure_canvas` of `~kivyplotlib.widgets.MatplotFigure` 
        object to method `_canvas_ready_`. Fired when value 
        `figure_widget` changes."""
        self.figure_widget.bind(figure_canvas=self._canvas_ready_) # type: ignore
        self.coordinate_button.bind(active=figure_widget.setter('show_info')) # type: ignore
    
    def show_coordinate(self, *args) -> None:
        """Show xy coordinate. Callback function bound to `on_release`
        of `coordinate_button`."""
        if self.figure_widget is None:
            return
        
        if self.coordinate_button.active:
            self._reset_mode_()
    
    def _reset_mode_(self) -> None:
        """Reset navigation mode to `_Mode.None`."""
        if self.navigation.mode == _Mode.NONE:
            return
        
        if self.navigation.mode == _Mode.ZOOM:
            self.navigation.zoom()
        elif self.navigation.mode == _Mode.PAN:
            self.navigation.pan()

    def _canvas_ready_(
            self, figure_widget: MatplotFigure, canvas: FigureCanvas) -> None:
        """Called when attribute `figure_canvas` of `figure_widget` 
        changes."""
        self.navigation = Navigation(canvas, self)
        self.navigation.figure_widget = figure_widget # type: ignore
        self.home_button.bind(on_release=self.navigation.home)
        self.back_button.bind(on_release=self.navigation.back)
        self.forward_button.bind(on_release=self.navigation.forward)
        self.pan_button.bind(on_release=self.navigation.pan)
        self.zoom_button.bind(on_release=self.navigation.zoom)


class Chart(RelativeLayout):

    figure: Figure = ObjectProperty(None)
    """Reference to `~matplotlib.figure.Figure` object."""

    toolbar: Toolbar = ObjectProperty(None)
    """Reference to `~kivyplotlib.widgets.Toolbar` object."""

    figure_widget: MatplotFigure = ObjectProperty(None)
    """Reference to `~kivyplotlib.widgets.MatplotFigure` object."""

    kw_save: Dict[str, Any]
    """Keyword arguments for 
    `~kivyplotlib.widgets.MatplotFigure.save_figure` method."""

    default_dir: Path = Path.home()/'Downloads'
    """Default directory to save figure to. You can change this 
    attribute to save figure to a different directory."""

    filename: str = StringProperty('')
    """Filename to save figure to. If empty, use default filename."""

    initial: str = ''
    """Initial directory to save figure to. This attribute saves the
    last directory for the saved figure. This can be used when using a 
    file browser to start from the same directory again."""

    def __init__(self, kw_save: Dict[str, Any] = {}, **kwargs) -> None:
        _kwargs = dict(
            # anchor_x='right',
            # anchor_y='top',
            ) | kwargs
        self.kw_save = kw_save
        super().__init__(**_kwargs)
        self.info_label = InfoLabel()
        self.toolbar = Toolbar(self.info_label)
        self.figure_widget = MatplotFigure(toolbar=self.toolbar)
        self.toolbar.figure_widget = self.figure_widget
        self.add_widget(self.figure_widget)
        self.add_widget(self.toolbar)
        self.add_widget(self.toolbar.menu)
        self.add_widget(self.info_label)
        self.toolbar.save_figure_button.bind(on_release=self.save_figure)

    def on_figure(self, caller: Self, figure: Figure) -> None:
        """Callback function, called when `figure` attribute changes.
        Set `figure_widget.figure` attribute."""
        self.figure_widget.figure = figure

    def get_save_dir(self) -> str | Path | None:
        """Get directory to save figure to. Override this method to 
        change default directory."""
        return self.default_dir
    
    def save_figure(self, *args) -> None:
        """Save figure to file. Override the `get_save_dir` method to 
        browse for a folder or change the default directory at 
        `default_dir` attribute. Also change the 'filename' attribute or
        pass a valid filename via 'fname' key in `kw_save'.
        
        Raises
        ------
        FileNotFoundError
            If default directory is not a directory.
        """
        save_dir = self.get_save_dir()
        if save_dir is None or not Path(save_dir).is_dir():
            save_dir = Path(self.default_dir)
            if not save_dir.is_dir():
                raise FileNotFoundError(
                    f'{save_dir} is not a directory.')
        else:
            save_dir = Path(save_dir)

        self.initial = save_dir.as_posix()
        filename = self.kw_save.pop('fname', self.filename)
        if not filename:
            filename = self.figure.canvas.get_default_filename()
        suffix = self.kw_save.get('format', Path(filename).suffix.lstrip('.'))
        
        save_path = save_dir/f'{filename}.{suffix}'
        self.figure.savefig(save_path, **self.kw_save)


__all__ = [
    MatplotFigure.__name__,
    IconToggleButton.__name__,
    Toolbar.__name__,
    Chart.__name__
]