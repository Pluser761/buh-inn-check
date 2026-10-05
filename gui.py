"""
Графический интерфейс к check_inn.py.

Главное окно — ввод ИНН (вручную или из файла). По кнопке «Проверить» ИНН проверяются,
и для каждого статуса, в котором нашлись организации, открывается отдельное окно.

Запуск:
    python gui.py                          # токен DaData вводится в окне
    DADATA_MOCK=1 python gui.py            # без запросов, через mock_dadata.py
"""

import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import check_inn

# порядок открытия окон; статусы не из списка (неизвестные DaData) идут в конце
STATUS_ORDER = [
    "действующая",
    "ликвидируется",
    "ликвидирована",
    "банкротство",
    "в процессе реорганизации",
    "не найдена",
    "некорректный ИНН",
    "ошибка запроса",
]


def parse_inns(text: str) -> list[str]:
    inns = ["".join(ch for ch in line if ch.isdigit()) for line in text.splitlines()]
    # убираем пустые строки и дубли, сохраняя порядок
    return list(dict.fromkeys(i for i in inns if i))

# настройки (токен) — в домашней папке, чтобы не вводить заново при каждом запуске
SETTINGS_FILE = Path.home() / ".check_inn_gui.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

# Стандартные Cmd/Ctrl+V/C/X/A/Z в Tk срабатывают только в английской раскладке —
# в русской клавиша V приходит как «м». Дублируем их для русских букв.
MOD = "Command" if sys.platform == "darwin" else "Control"
RU_SHORTCUTS = {
    "м": "<<Paste>>", "с": "<<Copy>>", "ч": "<<Cut>>", "ф": "<<SelectAll>>", "я": "<<Undo>>",
}
RU_KEYSYMS = {
    "Cyrillic_em": "м", "Cyrillic_es": "с", "Cyrillic_che": "ч",
    "Cyrillic_ef": "ф", "Cyrillic_ya": "я",
}


def on_ru_shortcut(event):
    char = RU_KEYSYMS.get(event.keysym, event.char.lower())
    virtual = RU_SHORTCUTS.get(char)
    if virtual and isinstance(event.widget, (tk.Text, tk.Entry, ttk.Entry)):
        event.widget.event_generate(virtual)
        return "break"


def show_edit_menu(event):
    widget = event.widget
    widget.focus_set()
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Выделить всё",
                     command=lambda: widget.event_generate("<<SelectAll>>"))
    menu.tk_popup(event.x_root, event.y_root)


def enable_editing(widget):
    """Правый клик — меню правки (на macOS это Button-2 или Ctrl+клик)."""
    buttons = ("<Button-2>", "<Control-Button-1>") if sys.platform == "darwin" else ("<Button-3>",)
    for button in buttons:
        widget.bind(button, show_edit_menu)


class ResultWindow(tk.Toplevel):
    def __init__(self, master, status: str, rows: list[tuple[str, str]], offset: int):
        super().__init__(master)
        self.status = status
        self.rows = rows
        self.title(f"{status} — {len(rows)}")
        self.geometry(f"640x400+{120 + offset * 30}+{120 + offset * 30}")

        second = "Ошибка" if status == "ошибка запроса" else "Наименование"
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(frame, columns=("inn", "name"), show="headings")
        tree.heading("inn", text="ИНН")
        tree.heading("name", text=second)
        tree.column("inn", width=120, stretch=False)
        tree.column("name", width=480)
        for row in rows:
            tree.insert("", "end", values=row)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Копировать", command=self.copy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Сохранить…", command=self.save).pack(side="left")

    def as_text(self) -> str:
        return "".join(f"{inn}\t{name}\t{self.status}\n" for inn, name in self.rows)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.as_text())

    def save(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt", initialfile=f"{self.status}.txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.as_text())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Проверка ИНН" + (" [МОК]" if check_inn.MOCK else ""))
        self.geometry("420x580")
        self.events: queue.Queue = queue.Queue()
        self.result_windows: list[ResultWindow] = []
        self.bind_all(f"<{MOD}-KeyPress>", on_ru_shortcut)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Токен DaData:").pack(anchor="w")
        self.token_entry = ttk.Entry(frame)
        self.token_entry.insert(0, load_settings().get("token", ""))
        self.token_entry.pack(fill="x", pady=(4, 10))
        enable_editing(self.token_entry)

        ttk.Label(frame, text="ИНН — по одному в строке:").pack(anchor="w")

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(4, 8))
        self.text = tk.Text(text_frame, wrap="none", undo=True)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        enable_editing(self.text)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.load_btn = ttk.Button(buttons, text="Загрузить из файла…", command=self.load_file)
        self.load_btn.pack(side="left")
        self.check_btn = ttk.Button(buttons, text="Проверить", command=self.start_check)
        self.check_btn.pack(side="right")

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 2))
        self.status_label = ttk.Label(frame, text="", wraplength=400)
        self.status_label.pack(anchor="w")

    def save_token(self):
        save_settings({**load_settings(), "token": self.token_entry.get().strip()})

    def on_close(self):
        self.save_token()
        self.destroy()

    def load_file(self):
        path = filedialog.askopenfilename(
            parent=self, filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            with open(path, encoding="utf-8") as f:
                self.text.delete("1.0", "end")
                self.text.insert("1.0", f.read())

    def start_check(self):
        inns = parse_inns(self.text.get("1.0", "end"))
        if not inns:
            messagebox.showwarning("Нет данных", "Введите хотя бы один ИНН.", parent=self)
            return
        token = self.token_entry.get().strip()
        self.save_token()
        if not check_inn.MOCK and not token:
            messagebox.showerror("Нет токена", "Введите токен DaData.", parent=self)
            return

        for w in self.result_windows:
            if w.winfo_exists():
                w.destroy()
        self.result_windows.clear()

        self.check_btn.configure(state="disabled")
        self.load_btn.configure(state="disabled")
        self.progress.configure(maximum=len(inns), value=0)
        self.status_label.configure(text=f"Проверено 0 из {len(inns)}")

        threading.Thread(target=self.worker, args=(inns, token), daemon=True).start()
        self.after(100, self.poll)

    def worker(self, inns: list[str], token: str):
        # работает в фоновом потоке; с виджетами общается только через очередь
        results: dict[str, list[tuple[str, str]]] = {}
        for n, inn in enumerate(inns, 1):
            name, status = check_inn.check(inn, token)
            results.setdefault(status, []).append((inn, name))
            self.events.put(("progress", n, len(inns)))
            time.sleep(check_inn.REQUEST_DELAY)  # лимит DaData — до 30 запросов в секунду
        self.events.put(("done", results))

    def poll(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "progress":
                _, n, total = event
                self.progress.configure(value=n)
                self.status_label.configure(text=f"Проверено {n} из {total}")
            else:
                self.finish(event[1])
                return
        self.after(100, self.poll)

    def finish(self, results: dict[str, list[tuple[str, str]]]):
        self.check_btn.configure(state="normal")
        self.load_btn.configure(state="normal")

        statuses = sorted(results, key=lambda s: (
            STATUS_ORDER.index(s) if s in STATUS_ORDER else len(STATUS_ORDER), s))
        summary = ", ".join(f"{s}: {len(results[s])}" for s in statuses)
        self.status_label.configure(text=summary)

        # окна открываются только для статусов, где есть организации
        for offset, status in enumerate(statuses):
            self.result_windows.append(ResultWindow(self, status, results[status], offset))


if __name__ == "__main__":
    App().mainloop()
