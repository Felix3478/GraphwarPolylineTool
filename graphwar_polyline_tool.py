from __future__ import annotations

import json
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import messagebox


EPS = 1e-9
GAME_MIN_X = -25.0
GAME_MAX_X = 25.0
GAME_MIN_Y = -15.0
GAME_MAX_Y = 15.0
CONFIG_PATH = Path(__file__).with_name("graphwar_polyline_calibration.json")
OVERLAY_PATH_COLOR = "#ff2a2a"
OVERLAY_TEXT_COLOR = "#ff2a2a"


class PolylineError(ValueError):
    pass


@dataclass(frozen=True)
class CalibrationBox:
    left: float
    top: float
    right: float
    bottom: float

    def normalized(self) -> "CalibrationBox":
        left = min(self.left, self.right)
        right = max(self.left, self.right)
        top = min(self.top, self.bottom)
        bottom = max(self.top, self.bottom)
        if nearly_equal(left, right) or nearly_equal(top, bottom):
            raise ValueError("校准区域宽度和高度必须大于 0。")
        return CalibrationBox(left=left, top=top, right=right, bottom=bottom)


def nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) <= EPS


def screen_to_game(px: float, py: float, box: CalibrationBox) -> tuple[float, float]:
    box = box.normalized()
    game_x = GAME_MIN_X + (px - box.left) / (box.right - box.left) * (GAME_MAX_X - GAME_MIN_X)
    game_y = GAME_MAX_Y - (py - box.top) / (box.bottom - box.top) * (GAME_MAX_Y - GAME_MIN_Y)
    return round_near_zero(game_x), round_near_zero(game_y)


def game_to_screen(x: float, y: float, box: CalibrationBox) -> tuple[float, float]:
    box = box.normalized()
    px = box.left + (x - GAME_MIN_X) / (GAME_MAX_X - GAME_MIN_X) * (box.right - box.left)
    py = box.top + (GAME_MAX_Y - y) / (GAME_MAX_Y - GAME_MIN_Y) * (box.bottom - box.top)
    return px, py


def points_to_polyline(points: list[tuple[float, float]]) -> str:
    if not points:
        raise PolylineError("至少需要一个点。")

    sorted_points = sorted(points, key=lambda point: point[0])
    unique_points: list[tuple[float, float]] = []

    for x, y in sorted_points:
        if unique_points and nearly_equal(unique_points[-1][0], x):
            if not nearly_equal(unique_points[-1][1], y):
                raise PolylineError("存在相同横坐标但纵坐标不同的点。")
            continue
        unique_points.append((round_near_zero(x), round_near_zero(y)))

    if len(unique_points) == 1:
        return format_number(unique_points[0][1])

    terms = [format_number(unique_points[0][1])]
    for index in range(len(unique_points) - 1):
        x1, y1 = unique_points[index]
        x2, y2 = unique_points[index + 1]
        if nearly_equal(y1, y2):
            continue

        coefficient = (y2 - y1) / (2.0 * (x2 - x1))
        inner = (
            f"{abs_call(x1)}-{abs_call(x2)}+{format_number(x2 - x1)}"
        )
        term = multiply(coefficient, f"({inner})")
        terms.append(term)

    return join_terms(terms)


def round_near_zero(value: float) -> float:
    if nearly_equal(value, 0.0):
        return 0.0
    return value


def format_number(value: float) -> str:
    value = round_near_zero(value)
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def x_minus(value: float) -> str:
    value = round_near_zero(value)
    if nearly_equal(value, 0.0):
        return "x"
    if value > 0:
        return f"x-{format_number(value)}"
    return f"x+{format_number(abs(value))}"


def abs_call(center_x: float) -> str:
    return f"abs({x_minus(center_x)})"


def multiply(coefficient: float, expression: str) -> str:
    coefficient = round_near_zero(coefficient)
    if nearly_equal(coefficient, 1.0):
        return expression
    if nearly_equal(coefficient, -1.0):
        return f"-{expression}"
    return f"{format_number(coefficient)}*{expression}"


def join_terms(terms: list[str]) -> str:
    output = terms[0]
    for term in terms[1:]:
        if term.startswith("-"):
            output += term
        else:
            output += f"+{term}"
    return output


class ClickOverlay:
    def __init__(
        self,
        root: tk.Tk,
        prompt: str,
        on_click,
        on_cancel=None,
        close_on_click: bool = True,
        escape_label: str = "Esc 取消",
        calibration: CalibrationBox | None = None,
        points: list[tuple[float, float]] | None = None,
    ) -> None:
        self.root = root
        self.on_click = on_click
        self.on_cancel = on_cancel
        self.close_on_click = close_on_click
        self.escape_label = escape_label
        self.calibration = calibration
        self.points = points if points is not None else []

        self.window = tk.Toplevel(root)
        self.window.title("Graphwar II 点选覆盖层")
        self.window.attributes("-fullscreen", True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.35)
        self.window.configure(bg="#111111")
        self.window.bind("<Escape>", self.cancel)
        self.window.bind("<Button-1>", self.clicked)

        self.canvas = tk.Canvas(self.window, highlightthickness=0, bg="#111111")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.clicked)
        self.window.after(50, lambda: self.window.focus_force())

        self.prompt = prompt
        self.canvas.create_text(
            24,
            24,
            anchor="nw",
            text=f"{prompt}\n{escape_label}",
            fill=OVERLAY_TEXT_COLOR,
            font=("Microsoft YaHei UI", 15, "bold"),
        )
        self.draw_existing_geometry()

    def draw_existing_geometry(self) -> None:
        self.canvas.delete("geometry")
        if not self.calibration:
            return

        box = self.calibration.normalized()
        self.canvas.create_rectangle(
            box.left,
            box.top,
            box.right,
            box.bottom,
            outline="#49d17d",
            width=2,
            tags=("geometry",),
        )

        for index, point in enumerate(self.points, start=1):
            px, py = game_to_screen(point[0], point[1], box)
            self.canvas.create_oval(
                px - 4,
                py - 4,
                px + 4,
                py + 4,
                fill=OVERLAY_PATH_COLOR,
                outline="",
                tags=("geometry",),
            )
            self.canvas.create_text(
                px + 8,
                py - 8,
                text=str(index),
                anchor="sw",
                fill=OVERLAY_TEXT_COLOR,
                font=("Microsoft YaHei UI", 10, "bold"),
                tags=("geometry",),
            )

        if len(self.points) >= 2:
            screen_points = []
            for point in sorted(self.points, key=lambda item: item[0]):
                screen_points.extend(game_to_screen(point[0], point[1], box))
            self.canvas.create_line(*screen_points, fill=OVERLAY_PATH_COLOR, width=2, tags=("geometry",))

    def clicked(self, event) -> None:
        self.on_click(event.x_root, event.y_root)
        if self.close_on_click:
            self.window.destroy()
        else:
            self.draw_existing_geometry()
        return "break"

    def cancel(self, _event=None) -> None:
        self.window.destroy()
        if self.on_cancel:
            self.on_cancel()
        return "break"


class GraphwarPolylineApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Graphwar II 折线工具")
        self.root.geometry("520x560")
        self.root.resizable(False, False)

        self.pending_top_left: tuple[float, float] | None = None
        self.calibration: CalibrationBox | None = self.load_calibration()
        self.points: list[tuple[float, float]] = []
        self.expression_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

        self.build_ui()
        self.refresh()

    def build_ui(self) -> None:
        padding = {"padx": 12, "pady": 6}

        title = tk.Label(
            self.root,
            text="Graphwar II 折线工具",
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        )
        title.pack(fill=tk.X, padx=12, pady=(12, 2))

        hint = tk.Label(
            self.root,
            text="先框选白色作图区左上角和右下角，再在游戏画面上点路径点。",
            anchor="w",
            justify=tk.LEFT,
        )
        hint.pack(fill=tk.X, padx=12, pady=(0, 8))

        top_buttons = tk.Frame(self.root)
        top_buttons.pack(fill=tk.X, **padding)
        tk.Button(top_buttons, text="框选作图区", command=self.start_calibration).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top_buttons, text="添加点", command=self.add_point).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top_buttons, text="清空并添加点", command=self.clear_and_add_points).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top_buttons, text="撤销点", command=self.undo_point).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top_buttons, text="清空点", command=self.clear_points).pack(side=tk.LEFT)

        second_buttons = tk.Frame(self.root)
        second_buttons.pack(fill=tk.X, **padding)
        tk.Button(second_buttons, text="生成并复制", command=self.generate_and_copy).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(second_buttons, text="重置校准", command=self.reset_calibration).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(second_buttons, text="退出", command=self.root.destroy).pack(side=tk.LEFT)

        self.status_label = tk.Label(self.root, textvariable=self.status_var, anchor="w", justify=tk.LEFT)
        self.status_label.pack(fill=tk.X, padx=12, pady=(8, 2))

        tk.Label(self.root, text="点列表", anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(
            fill=tk.X, padx=12, pady=(8, 2)
        )
        self.points_box = tk.Listbox(self.root, height=9)
        self.points_box.pack(fill=tk.X, padx=12)

        tk.Label(self.root, text="生成结果", anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(
            fill=tk.X, padx=12, pady=(12, 2)
        )
        self.expression_text = tk.Text(self.root, height=7, wrap=tk.WORD)
        self.expression_text.pack(fill=tk.BOTH, padx=12, pady=(0, 12))

    def start_calibration(self) -> None:
        self.pending_top_left = None
        self.root.withdraw()

        def first_click(px: float, py: float) -> None:
            self.pending_top_left = (px, py)
            self.root.after(150, self.ask_bottom_right)

        ClickOverlay(
            self.root,
            "点击作图区左上角",
            first_click,
            self.cancel_overlay,
            True,
            "Esc 取消",
            self.calibration,
            self.points,
        )

    def ask_bottom_right(self) -> None:
        def second_click(px: float, py: float) -> None:
            if not self.pending_top_left:
                return
            left, top = self.pending_top_left
            try:
                self.calibration = CalibrationBox(left=left, top=top, right=px, bottom=py).normalized()
                self.save_calibration()
            except ValueError as error:
                messagebox.showerror("校准失败", str(error))
            finally:
                self.pending_top_left = None
                self.root.deiconify()
                self.refresh()

        ClickOverlay(
            self.root,
            "点击作图区右下角",
            second_click,
            self.cancel_overlay,
            True,
            "Esc 取消",
            self.calibration,
            self.points,
        )

    def add_point(self) -> None:
        if not self.calibration:
            messagebox.showwarning("需要校准", "请先框选作图区。")
            return

        self.root.withdraw()

        def point_click(px: float, py: float) -> None:
            self.append_screen_point(px, py)

        ClickOverlay(
            self.root,
            "连续点击路径点；按 Esc 结束并复制函数",
            point_click,
            self.finish_point_collection,
            False,
            "Esc 结束并复制",
            self.calibration,
            self.points,
        )

    def clear_and_add_points(self) -> None:
        self.points.clear()
        self.refresh()
        self.add_point()

    def append_screen_point(self, px: float, py: float) -> None:
        if not self.calibration:
            raise ValueError("请先框选作图区。")
        self.points.append(screen_to_game(px, py, self.calibration))
        self.refresh()

    def finish_point_collection(self) -> None:
        self.root.deiconify()
        self.generate_and_copy()

    def cancel_overlay(self) -> None:
        self.pending_top_left = None
        self.root.deiconify()
        self.refresh()

    def undo_point(self) -> None:
        if self.points:
            self.points.pop()
            self.refresh()

    def clear_points(self) -> None:
        self.points.clear()
        self.refresh()

    def reset_calibration(self) -> None:
        self.calibration = None
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        self.refresh()

    def generate_and_copy(self) -> None:
        try:
            expression = points_to_polyline(self.points)
        except PolylineError as error:
            messagebox.showerror("无法生成折线", str(error))
            return

        self.expression_var.set(expression)
        self.expression_text.delete("1.0", tk.END)
        self.expression_text.insert("1.0", expression)
        self.root.clipboard_clear()
        self.root.clipboard_append(expression)
        self.status_var.set("已生成并复制到剪贴板。")

    def refresh(self) -> None:
        if self.calibration:
            box = self.calibration.normalized()
            calibration_text = (
                f"校准: 左上({format_number(box.left)}, {format_number(box.top)}) "
                f"右下({format_number(box.right)}, {format_number(box.bottom)})"
            )
        else:
            calibration_text = "校准: 未设置"
        self.status_var.set(f"{calibration_text}    点数: {len(self.points)}")

        self.points_box.delete(0, tk.END)
        for index, (x, y) in enumerate(self.points, start=1):
            self.points_box.insert(tk.END, f"{index}. x={format_number(x)}, y={format_number(y)}")

    def load_calibration(self) -> CalibrationBox | None:
        if not CONFIG_PATH.exists():
            return None
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return CalibrationBox(**data).normalized()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save_calibration(self) -> None:
        if not self.calibration:
            return
        CONFIG_PATH.write_text(json.dumps(asdict(self.calibration), indent=2), encoding="utf-8")


def main() -> None:
    root = tk.Tk()
    GraphwarPolylineApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
