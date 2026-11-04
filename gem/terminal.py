import copy
import errno
import os
from pathlib import Path
import queue
import signal
import struct
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, ttk

if os.name == "nt":
    pty = None
    termios = None
else:
    import pty
    import termios

from .drop import dropped_payload

try:
    import pyte
except ImportError:
    pyte = None

try:
    from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD
except ImportError:
    COPY = REFUSE_DROP = DND_FILES = TkinterDnD = None

if pyte is not None:
    class TerminalScreen(pyte.HistoryScreen):
        def report_device_status(self, mode, private=False):
            super().report_device_status(mode)


FG_COLORS = {
    "default": "#e6edf3", "black": "#0c1118", "red": "#ff7b72",
    "green": "#7ee787", "yellow": "#f2cc60", "blue": "#71b7ff",
    "magenta": "#d2a8ff", "cyan": "#76d7ea", "white": "#f0f6fc",
    "brightblack": "#7d8590", "brightred": "#ffa198",
    "brightgreen": "#aff5b4", "brightyellow": "#ffe38f",
    "brightblue": "#a5d6ff", "brightmagenta": "#e2c5ff",
    "brightcyan": "#a5f3fc", "brightwhite": "#ffffff",
}
BG_COLORS = {**FG_COLORS, "default": "#0c1118", "black": "#0c1118"}
KEY_SEQUENCES = {
    "BackSpace": b"\x7f", "Delete": b"\x1b[3~", "Return": b"\r",
    "KP_Enter": b"\r", "Tab": b"\t", "Up": b"\x1b[A", "Down": b"\x1b[B",
    "Right": b"\x1b[C", "Left": b"\x1b[D", "Home": b"\x1b[H",
    "End": b"\x1b[F", "Prior": b"\x1b[5~", "Next": b"\x1b[6~",
    "Insert": b"\x1b[2~", "Escape": b"\x1b",
}
for index in range(1, 13):
    KEY_SEQUENCES[f"F{index}"] = f"\x1bO{chr(ord('P') + index - 1)}".encode()


class TerminalPanel(ttk.Frame):
    def __init__(self, parent, workspace, command, status_callback, startup_text=""):
        super().__init__(parent)
        if pyte is None:
            raise ValueError("The embedded terminal requires pyte. Run: python -m pip install -e .")
        self.workspace = Path(workspace)
        self.command = command
        self.status_callback = status_callback
        self.startup_text = startup_text
        self.process = None
        self.fd = None
        self.read_queue = None
        self.reader_thread = None
        self.reader_eof = False
        self.exited = False
        self.reaped = False
        self.write_queue = bytearray()
        self.write_after_id = None
        self.parser_warning = None
        self.screen = TerminalScreen(80, 24, history=1000)
        self.stream = pyte.ByteStream(self.screen)
        self.columns = 80
        self.lines = 24
        self.tag_cache = set()
        self.font_family = tkfont.nametofont("TkFixedFont").cget("family")
        self.font_size = 10
        self.text = tk.Text(
            self, bg=BG_COLORS["default"], fg=FG_COLORS["default"],
            insertwidth=0, wrap="none", undo=False, takefocus=True,
            font=(self.font_family, self.font_size), borderwidth=0,
        )
        self.text.pack(fill="both", expand=True)
        self.text.bind("<Key>", self.on_key)
        self.text.bind("<Configure>", self.on_resize)
        self.text.bind("<Button-4>", lambda event: self.scroll_history(-1))
        self.text.bind("<Button-5>", lambda event: self.scroll_history(1))
        self.text.bind("<MouseWheel>", self.on_mousewheel)
        self.text.bind("<Control-Shift-C>", lambda event: self.text.event_generate("<<Copy>>") or "break")
        self.text.bind("<Control-Shift-V>", lambda event: self.paste())
        self.text.bind("<<Paste>>", lambda event: self.paste())
        self.text.bind("<<Cut>>", lambda event: "break")
        self.text.bind("<<Clear>>", lambda event: "break")
        self.text.bind("<Button-2>", lambda event: "break")
        self.text.bind("<Button-1>", lambda event: self.text.focus_set())
        self.closed = False
        self.drop_enabled = False
        self.poll_after_id = None
        self.render_after_id = None
        if command:
            self.configure_drop_target()
            self.after_idle(self.start)
        else:
            self.text.insert("1.0", "No AI agent configured.\n\nUse --agent kimi, --agent claude, --agent codex,\nor --agent-command 'your-agent --flag'.\n\nThe dashboard remains fully usable without an agent.")
            self.text.configure(state="disabled")
        self.poll_after_id = self.after(30, self.poll)
        self.render_after_id = self.after(60, self.render)

    def configure_drop_target(self):
        try:
            if TkinterDnD is None:
                raise RuntimeError("reinstall the package dependencies to restore tkinterdnd2")
            TkinterDnD._require(self.winfo_toplevel())
            self.text.drop_target_register(DND_FILES)
            self.text.dnd_bind("<<Drop>>", self.on_drop)
            self.drop_enabled = True
        except (AttributeError, RuntimeError, tk.TclError) as error:
            self.status_callback(f"File drag-and-drop unavailable: {error}")

    def submit_agent_request(self, text):
        if not self.command or self.fd is None or self.exited or self.closed:
            raise ValueError("The embedded agent is not running")
        if not text or any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise ValueError("Agent prompts cannot contain control characters")
        self.write(text.encode("utf-8"))
        self.write(b"\r")
        self.text.focus_set()

    def insert_dropped_paths(self, paths):
        if not self.command or self.fd is None or self.exited or self.closed:
            raise ValueError("Drop rejected: the embedded agent is not running")
        paths = tuple(paths)
        payload = dropped_payload(paths)
        self.write(payload)
        self.text.focus_set()
        return len(paths)

    def on_drop(self, event):
        try:
            paths = self.text.tk.splitlist(event.data)
            count = self.insert_dropped_paths(paths)
            self.status_callback(f"Inserted {count} path{'s' if count != 1 else ''}; review before running")
            return COPY
        except (OSError, ValueError, tk.TclError) as error:
            self.status_callback(str(error))
            return REFUSE_DROP

    def start(self):
        if self.closed or self.process is not None:
            return
        environment = os.environ.copy()
        package_root = str(Path(__file__).resolve().parent.parent)
        environment.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "PYTHONPATH": package_root + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""),
        })
        if os.name == "nt":
            environment.setdefault("PYTHONIOENCODING", "utf-8")
            environment.setdefault("PYTHONUTF8", "1")
            try:
                from winpty import PtyProcess
                self.process = PtyProcess.spawn(
                    self.command, cwd=str(self.workspace), env=environment,
                    dimensions=(self.lines, self.columns),
                )
            except (ImportError, OSError, RuntimeError) as error:
                self.status_callback(f"Unable to start agent: {error}")
                return
            self.fd = True
            self.read_queue = queue.Queue()
            self.reader_thread = threading.Thread(target=self._read_windows, daemon=True)
            self.reader_thread.start()
        else:
            try:
                pid, descriptor = pty.fork()
            except OSError as error:
                self.status_callback(f"Unable to start agent: {error}")
                return
            if pid == 0:
                try:
                    os.chdir(self.workspace)
                    os.execvpe(self.command[0], self.command, environment)
                except BaseException as error:
                    os.write(2, f"Unable to start agent: {error}\r\n".encode())
                    os._exit(127)
            self.process = pid
            self.fd = descriptor
            os.set_blocking(self.fd, False)
        terminal_kind = "ConPTY" if os.name == "nt" else "PTY"
        self.status_callback(f"Agent: {Path(self.command[0]).name} · interactive {terminal_kind}")
        if self.startup_text:
            self.write(self.startup_text.encode("utf-8"))
            self.write(b"\r")
        self.text.focus_set()
        self.resize_terminal()

    def _read_windows(self):
        try:
            while True:
                data = self.process.read(65536)
                if not data:
                    break
                self.read_queue.put(data.encode("utf-8"))
        except (EOFError, OSError):
            pass
        finally:
            self.read_queue.put(None)

    def poll(self):
        if self.fd is not None:
            if os.name == "nt":
                while True:
                    try:
                        data = self.read_queue.get_nowait()
                    except queue.Empty:
                        break
                    if data is None:
                        self.reader_eof = True
                        break
                    self._feed(data)
            else:
                while True:
                    try:
                        data = os.read(self.fd, 65536)
                    except BlockingIOError:
                        break
                    except OSError as error:
                        if error.errno == errno.EIO:
                            self.finish("Agent session closed")
                            break
                        self.finish(f"Agent read error: {error}")
                        break
                    if not data:
                        self.finish("Agent session closed")
                        break
                    self._feed(data)
        if self.process is not None and not self.reaped:
            if os.name == "nt":
                if not self.process.isalive():
                    self.reaped = True
            else:
                try:
                    pid, status = os.waitpid(self.process, os.WNOHANG)
                except ChildProcessError:
                    pid, status = self.process, 0
                if pid:
                    self.reaped = True
                    code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status
                    self.finish(f"Agent exited ({code})")
        if self.process is not None and os.name == "nt" and self.reaped and self.reader_eof:
            self.finish("Agent session closed")
        if not self.closed:
            self.poll_after_id = self.after(30, self.poll)

    def _feed(self, data):
        try:
            self.stream.feed(data)
        except Exception as error:
            warning = f"Terminal display warning: {error}"
            if warning != self.parser_warning:
                self.parser_warning = warning
                self.status_callback(warning)

    def finish(self, message):
        if self.exited:
            return
        self.exited = True
        if self.write_after_id is not None:
            try:
                self.after_cancel(self.write_after_id)
            except tk.TclError:
                pass
            self.write_after_id = None
        self.write_queue.clear()
        if self.fd is not None:
            if os.name != "nt":
                try:
                    os.close(self.fd)
                except OSError:
                    pass
            self.fd = None
        if not self.closed:
            self.status_callback(message)

    def signal_process(self, signal_number):
        if self.reaped:
            return
        if os.name == "nt":
            self.process.terminate(force=True)
            return
        try:
            os.killpg(self.process, signal_number)
        except ProcessLookupError:
            try:
                os.kill(self.process, signal_number)
            except ProcessLookupError:
                pass

    def wait_for_child(self, timeout):
        deadline = time.monotonic() + timeout
        if os.name == "nt":
            while self.process.isalive() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.reaped = not self.process.isalive()
            return self.reaped
        while True:
            try:
                pid, _ = os.waitpid(self.process, os.WNOHANG)
            except ChildProcessError:
                pid = 0
                self.reaped = True
            if pid:
                self.reaped = True
            if self.reaped or time.monotonic() >= deadline:
                return self.reaped
            time.sleep(0.02)

    def stop(self):
        if self.closed:
            return
        self.closed = True
        for attribute in ("poll_after_id", "render_after_id", "write_after_id"):
            identifier = getattr(self, attribute)
            if identifier is not None:
                try:
                    self.after_cancel(identifier)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        if self.drop_enabled:
            try:
                self.text.drop_target_unregister()
            except tk.TclError:
                pass
            self.drop_enabled = False
        self.write_queue.clear()
        if self.process is not None and not self.reaped:
            self.signal_process(getattr(signal, "SIGHUP", signal.SIGINT))
            if not self.wait_for_child(1.0):
                self.signal_process(signal.SIGKILL)
                if not self.wait_for_child(1.0):
                    try:
                        self.status_callback(f"Agent process {self.process} could not be reaped")
                    except tk.TclError:
                        pass
        if self.fd is not None:
            if os.name != "nt":
                try:
                    os.close(self.fd)
                except OSError:
                    pass
            self.fd = None
        if self.reader_thread is not None:
            self.reader_thread.join(timeout=1)
            self.reader_thread = None
        if os.name == "nt" and self.process is not None:
            self.process.close()
        self.exited = True

    def write(self, data):
        if self.fd is None or self.exited or self.closed:
            return
        self.write_queue.extend(data)
        self.flush_writes()

    def flush_writes(self):
        if self.write_after_id is not None:
            try:
                self.after_cancel(self.write_after_id)
            except tk.TclError:
                pass
            self.write_after_id = None
        if self.fd is None or self.exited or self.closed:
            return
        while self.write_queue:
            payload = bytes(self.write_queue)
            try:
                if os.name == "nt":
                    try:
                        text = payload.decode("utf-8")
                    except UnicodeDecodeError as error:
                        if error.end != len(payload):
                            raise
                        break
                    written = self.process.write(text)
                    if not isinstance(written, int) or isinstance(written, bool) or not 0 <= written <= len(payload):
                        raise ValueError("ConPTY returned an invalid byte count")
                else:
                    written = os.write(self.fd, payload)
            except (BlockingIOError, InterruptedError):
                break
            except (OSError, UnicodeError, ValueError) as error:
                self.finish(f"Agent write error: {error}")
                return
            if written <= 0:
                break
            del self.write_queue[:written]
        if self.write_queue and not self.closed:
            self.write_after_id = self.after(10, self.flush_writes)

    def on_key(self, event):
        if not self.command:
            return "break"
        self.text.focus_set()
        if event.state & 0x4 and len(event.keysym) == 1 and event.keysym.isascii() and event.keysym.isalpha():
            data = bytes([ord(event.keysym.casefold()) & 0x1F])
        elif event.keysym in KEY_SEQUENCES:
            data = KEY_SEQUENCES[event.keysym]
        elif event.char and event.char >= " " and event.keysym not in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}:
            data = event.char.encode("utf-8")
        else:
            return "break"
        if event.state & 0x8:
            data = b"\x1b" + data
        self.write(data)
        return "break"

    def paste(self):
        try:
            value = self.clipboard_get()
        except tk.TclError:
            return "break"
        data = value.encode("utf-8")
        if len(data) > 8 * 1024 * 1024:
            self.status_callback("Paste rejected: 8 MiB maximum")
            return "break"
        self.write(data)
        return "break"

    def scroll_history(self, direction):
        if direction < 0:
            self.screen.prev_page()
        else:
            self.screen.next_page()
        self.render(force=True)
        return "break"

    def on_mousewheel(self, event):
        return self.scroll_history(-1 if event.delta > 0 else 1)

    def on_resize(self, _event=None):
        self.resize_terminal()

    def resize_terminal(self):
        metrics = tkfont.Font(family=self.font_family, size=self.font_size)
        columns = max(20, self.text.winfo_width() // max(1, metrics.measure("M")))
        lines = max(4, self.text.winfo_height() // max(1, metrics.metrics("linespace")))
        if (columns, lines) == (self.columns, self.lines):
            return
        previous_lines = self.screen.lines
        previous_columns = self.screen.columns
        previous_cursor = copy.copy(self.screen.cursor)
        previous_buffer = copy.deepcopy(self.screen.buffer)
        previous_content = sum(bool(line.strip()) for line in self.screen.display)
        self.columns, self.lines = columns, lines
        self.screen.resize(lines, columns)
        if previous_content and lines < previous_lines:
            start = max(0, min(previous_cursor.y - lines + 1, previous_lines - lines))
            for line in range(lines):
                if start + line >= previous_lines:
                    break
                self.screen.buffer[line] = previous_buffer[start + line]
                for column in range(columns, previous_columns):
                    self.screen.buffer[line].pop(column, None)
            self.screen.cursor = previous_cursor
            self.screen.cursor.y = max(0, min(previous_cursor.y - start, lines - 1))
            self.screen.dirty.update(range(lines))
        if self.fd is not None:
            if os.name == "nt":
                self.process.setwinsize(lines, columns)
            else:
                import fcntl
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))
        self.render(force=True)

    def style_tag(self, character):
        foreground = FG_COLORS.get(character.fg, FG_COLORS["default"])
        background = BG_COLORS.get(character.bg, BG_COLORS["default"])
        if character.reverse:
            foreground, background = background, foreground
        key = (foreground, background, character.bold, character.italics, character.underscore, character.strikethrough)
        name = "style-" + "-".join(str(value) for value in key)
        if name not in self.tag_cache:
            font = tkfont.Font(family=self.font_family, size=self.font_size, weight="bold" if character.bold else "normal", slant="italic" if character.italics else "roman")
            self.text.tag_configure(name, foreground=foreground, background=background, font=font, underline=character.underscore, overstrike=character.strikethrough)
            self.tag_cache.add(name)
        return name

    def schedule_render(self):
        if self.closed or not self.command:
            return
        if self.render_after_id is not None:
            try:
                self.after_cancel(self.render_after_id)
            except tk.TclError:
                pass
        self.render_after_id = self.after(60, self.render)

    def render(self, force=False):
        if self.render_after_id is not None:
            try:
                self.after_cancel(self.render_after_id)
            except tk.TclError:
                pass
            self.render_after_id = None
        if self.closed or not self.command:
            return
        if not self.screen.dirty and not force:
            self.schedule_render()
            return
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.yview_moveto(0.0)
        for line in range(self.lines):
            for column in range(self.columns):
                character = self.screen.buffer[line].get(column)
                if character is None:
                    self.text.insert("end", " ")
                else:
                    self.text.insert("end", character.data, (self.style_tag(character),))
            if line + 1 < self.lines:
                self.text.insert("end", "\n")
        if self.screen.history.position == self.screen.history.size and not getattr(self.screen.cursor, "hidden", False):
            start = f"{self.screen.cursor.y + 1}.{self.screen.cursor.x}"
            self.text.tag_add("terminal-cursor", start, f"{start} +1c")
            self.text.tag_configure("terminal-cursor", background=FG_COLORS["default"], foreground=BG_COLORS["default"])
        self.screen.dirty.clear()
        self.schedule_render()
