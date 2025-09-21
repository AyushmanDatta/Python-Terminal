#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyTerm — A Python-based terminal emulator
- Required: ls, cd, pwd, mkdir, rm (with robust error handling)
- Clean CLI interface with readable prompts and outputs
- Optional: natural language command translation ("ai" / "do"),
            command history & autocompletion, CPU/memory monitoring, process list

Dependencies:
- None required for core features.
- Optional:
    pip install prompt_toolkit psutil colorama
"""

from __future__ import annotations

import os
import sys
import re
import shlex
import stat
import time
import glob
import shutil
import errno
import difflib
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Tuple, Optional

# -------- Optional: color support (safe fallback if not installed) ----------
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
except Exception:
    class _Dummy:
        def __getattr__(self, _): return ""
    Fore = _Dummy()
    Style = _Dummy()

# -------- Optional: psutil for ps/sysmon (safe fallback if not installed) ----
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

# -------- Optional: prompt_toolkit for history/autocomplete ------------------
PTK_OK = False
try:
    from prompt_toolkit import PromptSession  # type: ignore
    from prompt_toolkit.history import FileHistory  # type: ignore
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory  # type: ignore
    from prompt_toolkit.completion import Completer, Completion, PathCompleter, FuzzyCompleter  # type: ignore
    PTK_OK = True
except Exception:
    PTK_OK = False


# --------------------- Utilities --------------------------------------------

def is_windows() -> bool:
    return os.name == "nt"


def format_bytes(n: int, human: bool) -> str:
    if not human:
        return str(n)
    # humanize
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(n)
    for u in units:
        if size < 1024.0 or u == units[-1]:
            return f"{size:.1f} {u}"
        size /= 1024.0


def filemode_bits(mode: int) -> str:
    # Similar to ls -l (e.g., -rw-r--r--)
    return stat.filemode(mode)


def safe_expand(path: str) -> Path:
    # Expand ~ and environment vars, normalize
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def colorize_name(p: Path) -> str:
    name = p.name
    try:
        if p.is_dir():
            return f"{Fore.BLUE}{name}{Style.RESET_ALL}"
        elif os.access(p, os.X_OK) and p.is_file():
            return f"{Fore.GREEN}{name}{Style.RESET_ALL}"
        else:
            return name
    except Exception:
        return name


def suggest_close(cmd: str, candidates: List[str]) -> str:
    matches = difflib.get_close_matches(cmd, candidates, n=3, cutoff=0.6)
    return (", ".join(matches)) if matches else ""


def parse_flags(args: List[str], short_long_map: Dict[str, str]) -> Tuple[set, List[str]]:
    """
    Parse simple flags; supports combined short flags: -lah -> -l -a -h
    short_long_map: map of all flags (short or long) to canonical short flag symbol
    Returns: (flags_set, remaining_args)
    """
    flags = set()
    rest = []
    i = 0
    shorts = {k for k in short_long_map if k.startswith("-") and not k.startswith("--")}
    longs = {k for k in short_long_map if k.startswith("--")}
    long_to_canon = {k: v for k, v in short_long_map.items()}
    short_to_canon = {k: v for k, v in short_long_map.items()}

    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if a in longs:
                flags.add(long_to_canon[a])
            else:
                rest.append(a)  # unknown long flag; leave for command to handle or error
        elif a.startswith("-") and a != "-":
            # Split combined short flags
            for ch in a[1:]:
                tok = "-" + ch
                if tok in shorts:
                    flags.add(short_to_canon[tok])
                else:
                    # Unknown short flag; keep as arg for later error
                    rest.append(a)
                    break
        else:
            rest.append(a)
        i += 1
    return flags, rest


def confirm(prompt: str) -> bool:
    try:
        resp = input(f"{prompt} [y/N]: ").strip().lower()
        return resp in ("y", "yes")
    except EOFError:
        return False


# --------------------- Natural Language Translator ---------------------------

class NLTranslator:
    """
    Very simple rule-based translator for natural language → commands.
    Examples:
      "create a folder test and move file1.txt into it"
        -> [["mkdir", "test"], ["mv", "file1.txt", "test/"]]
      "go to downloads then list" -> [["cd", "downloads"], ["ls"]]
      "delete build directory recursively" -> [["rm", "-r", "build"]]
    """
    def translate(self, text: str) -> List[List[str]]:
        # Normalize
        t = text.strip()
        if not t:
            return []
        # Split into clauses by connectors
        clauses = re.split(r"\b(?:and then|then|and|;)\b", t, flags=re.IGNORECASE)
        result: List[List[str]] = []

        for raw in clauses:
            s = raw.strip().lower()

            # Patterns:
            # create/make folder/dir NAME
            m = re.search(r"(?:create|make)\s+(?:a\s+)?(?:folder|directory|dir)\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                name = m.group(1).strip().strip('"\'')
                result.append(["mkdir", name])
                continue

            # create file NAME or touch NAME
            m = re.search(r"(?:create|make|touch)\s+(?:a\s+)?(?:file\s+)?(.+)$", s, flags=re.IGNORECASE)
            if m and "folder" not in s and "directory" not in s and "dir" not in s:
                name = m.group(1).strip().strip('"\'')
                result.append(["touch", name])
                continue

            # move X into/to Y
            m = re.search(r"move\s+(.+?)\s+(?:into|to|inside)\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                src = m.group(1).strip().strip('"\'')
                dst = m.group(2).strip().strip('"\'')
                result.append(["mv", src, dst])
                continue

            # copy X to Y
            m = re.search(r"copy\s+(.+?)\s+to\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                src = m.group(1).strip().strip('"\'')
                dst = m.group(2).strip().strip('"\'')
                result.append(["cp", src, dst])
                continue

            # delete/remove NAME (recursively?)
            m = re.search(r"(?:delete|remove|rm)\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                target = m.group(1).strip().strip('"\'')
                if re.search(r"recurs|folder|directory|dir", s):
                    result.append(["rm", "-r", target])
                else:
                    result.append(["rm", target])
                continue

            # go to / change directory
            m = re.search(r"(?:go\s+to|goto|open|enter|cd)\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                path = m.group(1).strip().strip('"\'')
                result.append(["cd", path])
                continue

            # list (here / in PATH)
            if re.fullmatch(r"(?:list|show\s+files|ls)", s):
                result.append(["ls"])
                continue
            m = re.search(r"(?:list|show)\s+(?:files\s+)?in\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                path = m.group(1).strip().strip('"\'')
                result.append(["ls", path])
                continue

            # where am i / current folder
            if re.search(r"(?:where\s+am\s+i|current\s+(?:dir|folder)|pwd)", s):
                result.append(["pwd"])
                continue

            # fallback: try to run as-is single word command
            words = shlex.split(raw.strip())
            if words:
                result.append(words)

        return result


# --------------------- Command framework ------------------------------------

@dataclass
class Command:
    name: str
    handler: Callable[[List[str]], int]
    usage: str
    help: str
    aliases: List[str] = field(default_factory=list)


class PyTerm:
    def __init__(self) -> None:
        self.commands: Dict[str, Command] = {}
        self.alias_to_name: Dict[str, str] = {}
        self.history_path = Path.home() / ".pyterm_history"
        self.cwd = Path.cwd()
        self.prompt_session: Optional[PromptSession] = None
        self.ptk = PTK_OK
        self.translator = NLTranslator()
        self._register_builtins()
        self._init_input()

    # ---------------- Input handling (with optional prompt_toolkit) ----------

    def _init_input(self) -> None:
        if self.ptk:
            try:
                # Autocomplete: filenames + known commands
                class SimpleCompleter(Completer):
                    def __init__(self, cmd_names: List[str]) -> None:
                        self.cmd_names = cmd_names
                        self.path_completer = PathCompleter(expanduser=True)

                    def get_completions(self, document, complete_event):
                        text = document.text_before_cursor
                        parts = shlex.split(text) if text.strip() else []
                        if not parts:
                            # top-level commands
                            for c in self.cmd_names:
                                if c.startswith(document.text_before_cursor.strip()):
                                    yield Completion(c, start_position=-len(document.text_before_cursor.strip()))
                            return
                        if len(parts) == 1 and not text.endswith(" "):
                            # completing command name
                            prefix = parts[0]
                            for c in self.cmd_names:
                                if c.startswith(prefix):
                                    yield Completion(c, start_position=-len(prefix))
                            return
                        # otherwise complete path for last token
                        for comp in self.path_completer.get_completions(document, complete_event):
                            yield comp

                self.prompt_session = PromptSession(
                    history=FileHistory(str(self.history_path)),
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=FuzzyCompleter(SimpleCompleter(sorted(self.commands.keys())))
                )
            except Exception:
                # fallback to plain input if PTK misbehaves
                self.ptk = False
                self.prompt_session = None

    def _input(self, prompt: str) -> str:
        if self.prompt_session:
            return self.prompt_session.prompt(prompt)
        return input(prompt)

    # ---------------- Command registration -----------------------------------

    def register(self, cmd: Command) -> None:
        self.commands[cmd.name] = cmd
        for al in cmd.aliases:
            self.alias_to_name[al] = cmd.name

    def _register_builtins(self) -> None:
        self.register(Command(
            "help", self._cmd_help,
            usage="help [command]",
            help="Show help for commands."
        ))
        self.register(Command(
            "exit", self._cmd_exit,
            usage="exit",
            help="Exit the terminal.",
            aliases=["quit", "q"]
        ))
        self.register(Command(
            "pwd", self._cmd_pwd,
            usage="pwd",
            help="Print current working directory."
        ))
        self.register(Command(
            "cd", self._cmd_cd,
            usage="cd [path]",
            help="Change directory. Use without args to go to home."
        ))
        self.register(Command(
            "ls", self._cmd_ls,
            usage="ls [-a] [-l] [-h] [path]",
            help="List files. -a show hidden, -l long format, -h human sizes."
        ))
        self.register(Command(
            "mkdir", self._cmd_mkdir,
            usage="mkdir [-p] path ...",
            help="Create directories. -p creates parents if needed."
        ))
        self.register(Command(
            "rm", self._cmd_rm,
            usage="rm [-r] [-f] target ...",
            help="Remove files or directories. -r recursive, -f force (no prompt)."
        ))
        # Optional but useful for NL and usability
        self.register(Command(
            "mv", self._cmd_mv,
            usage="mv src ... dest",
            help="Move/rename files or directories."
        ))
        self.register(Command(
            "cp", self._cmd_cp,
            usage="cp [-r] src ... dest",
            help="Copy files or directories. -r for directories."
        ))
        self.register(Command(
            "touch", self._cmd_touch,
            usage="touch file ...",
            help="Create empty file(s) or update modified time."
        ))
        self.register(Command(
            "cat", self._cmd_cat,
            usage="cat file ...",
            help="Print file contents."
        ))
        self.register(Command(
            "clear", self._cmd_clear,
            usage="clear",
            help="Clear the screen.",
            aliases=["cls"] if is_windows() else []
        ))
        self.register(Command(
            "which", self._cmd_which,
            usage="which command",
            help="Locate a command in PATH."
        ))
        # Natural language interface
        self.register(Command(
            "ai", self._cmd_ai,
            usage='ai "instruction sentence..."',
            help="Translate a natural sentence to commands and run it.",
            aliases=["do"]
        ))
        # Monitoring / process (optional with psutil)
        self.register(Command(
            "ps", self._cmd_ps,
            usage="ps",
            help="List running processes (best with psutil)."
        ))
        self.register(Command(
            "sysmon", self._cmd_sysmon,
            usage="sysmon [-w [seconds]]",
            help="Show CPU/Memory. Use -w (watch) to refresh."
        ))
        # Built-in history viewer (works even without prompt_toolkit)
        self.register(Command(
            "history", self._cmd_history,
            usage="history [n]",
            help="Show the last n commands (default 50)."
        ))

    # ---------------- Command dispatch ---------------------------------------

    def dispatch(self, line: str) -> int:
        line = line.strip()
        if not line:
            return 0
        try:
            parts = shlex.split(line)
        except Exception as e:
            print(f"Parse error: {e}")
            return 2

        name = parts[0]
        args = parts[1:]

        # Alias resolution
        if name in self.alias_to_name:
            name = self.alias_to_name[name]

        if name not in self.commands:
            suggestion = suggest_close(name, list(self.commands.keys()))
            msg = f"Unknown command: {name}"
            if suggestion:
                msg += f" (did you mean: {suggestion}?)"
            print(msg)
            return 127

        try:
            return self.commands[name].handler(args)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            return 130
        except SystemExit as se:
            # Stop program
            raise se
        except Exception as e:
            # Robust error handling
            print(f"Error: {e}")
            return 1

    # ----------------- Run loop ----------------------------------------------

    def prompt_str(self) -> str:
        cwd_disp = str(self.cwd)
        base = cwd_disp if len(cwd_disp) < 64 else "…" + cwd_disp[-63:]
        prompt = f"{Fore.CYAN}{base}{Style.RESET_ALL} $ "
        return prompt

    def run(self) -> None:
        print(f"{Fore.MAGENTA}PyTerm — Python Terminal. Type 'help' to start. 'exit' to quit.{Style.RESET_ALL}")
        while True:
            try:
                # Keep process CWD in sync (so os functions operate correctly)
                os.chdir(self.cwd)
                line = self._input(self.prompt_str())
                if self.prompt_session:
                    # prompt_toolkit saves to history automatically
                    pass
                else:
                    # manual history append
                    try:
                        self.history_path.parent.mkdir(parents=True, exist_ok=True)
                        with self.history_path.open("a", encoding="utf-8") as f:
                            f.write(line + "\n")
                    except Exception:
                        pass
                self.dispatch(line)
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue

    # ---------------- Built-in command implementations -----------------------

    def _cmd_help(self, args: List[str]) -> int:
        if not args:
            # List commands
            names = sorted(self.commands.keys())
            print("Available commands:")
            for n in names:
                c = self.commands[n]
                alias_str = (f" (aliases: {', '.join(c.aliases)})" if c.aliases else "")
                print(f"  {n:<8} - {c.help}{alias_str}")
            print("\nType 'help <command>' for usage.")
            return 0

        name = args[0]
        if name in self.alias_to_name:
            name = self.alias_to_name[name]
        if name in self.commands:
            c = self.commands[name]
            print(f"Usage: {c.usage}\n{c.help}")
            return 0

        print(f"No such command: {name}")
        return 1

    def _cmd_exit(self, args: List[str]) -> int:
        raise SystemExit(0)

    def _cmd_pwd(self, args: List[str]) -> int:
        print(str(self.cwd))
        return 0

    def _cmd_cd(self, args: List[str]) -> int:
        path = safe_expand(args[0]) if args else Path.home()
        if not path.exists():
            print(f"No such directory: {path}")
            return 1
        if not path.is_dir():
            print(f"Not a directory: {path}")
            return 1
        self.cwd = path.resolve()
        return 0

    def _cmd_ls(self, args: List[str]) -> int:
        flags, rest = parse_flags(args, {
            "-a": "-a", "--all": "-a",
            "-l": "-l", "--long": "-l",
            "-h": "-h", "--human": "-h",
            "-1": "-1", "--one": "-1",
        })
        target = safe_expand(rest[0]) if rest else self.cwd
        if not target.exists():
            print(f"No such file or directory: {target}")
            return 1

        def list_one(p: Path) -> None:
            try:
                st = p.lstat()
                mode = filemode_bits(st.st_mode)
                size = format_bytes(st.st_size, human=("-h" in flags))
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
                name = colorize_name(p)
                print(f"{mode} {st.st_nlink:>2} {size:>8} {mtime} {name}")
            except Exception as e:
                print(f"[error] {p.name}: {e}")

        if target.is_file():
            if "-l" in flags:
                list_one(target)
            else:
                print(target.name)
            return 0

        # Directory listing
        try:
            entries = list(target.iterdir())
        except PermissionError:
            print(f"Permission denied: {target}")
            return 1
        except Exception as e:
            print(f"Error reading directory: {e}")
            return 1

        # Filter hidden unless -a
        show_all = "-a" in flags
        items = [e for e in entries if show_all or not e.name.startswith(".")]
        items.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

        if "-l" in flags:
            for p in items:
                list_one(p)
        else:
            names = [colorize_name(p) for p in items]
            if "-1" in flags:
                for n in names:
                    print(n)
            else:
                # simple multi-column print based on terminal width
                width = shutil.get_terminal_size((80, 20)).columns
                colw = max((len(re.sub(r"\x1b\\[[0-9;]*m", "", n)) for n in names), default=1) + 2
                cols = max(1, width // colw)
                for i, n in enumerate(names):
                    end = "\n" if (i + 1) % cols == 0 else ""
                    print(n.ljust(colw), end=end)
                if names:
                    print()
        return 0

    def _cmd_mkdir(self, args: List[str]) -> int:
        flags, rest = parse_flags(args, {"-p": "-p", "--parents": "-p"})
        if not rest:
            print("Usage: mkdir [-p] path ...")
            return 2
        code = 0
        for raw in rest:
            p = safe_expand(raw)
            try:
                if "-p" in flags:
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    p.mkdir()
            except FileExistsError:
                print(f"mkdir: {p}: already exists")
                code = 1
            except Exception as e:
                print(f"mkdir: {p}: {e}")
                code = 1
        return code

    def _cmd_rm(self, args: List[str]) -> int:
        flags, rest = parse_flags(args, {
            "-r": "-r", "--recursive": "-r",
            "-f": "-f", "--force": "-f",
        })
        if not rest:
            print("Usage: rm [-r] [-f] target ...")
            return 2
        code = 0
        for raw in rest:
            p = safe_expand(raw)
            if not p.exists() and "-f" in flags:
                continue
            if not p.exists():
                print(f"rm: {p}: no such file or directory")
                code = 1
                continue
            try:
                if p.is_dir() and not p.is_symlink():
                    if "-r" not in flags:
                        print(f"rm: {p}: is a directory (use -r)")
                        code = 1
                        continue
                    if "-f" not in flags:
                        if not confirm(f"rm -r: delete directory '{p}' recursively?"):
                            continue
                    shutil.rmtree(p)
                else:
                    if "-f" not in flags:
                        if not confirm(f"rm: delete file '{p}'?"):
                            continue
                    p.unlink()
            except PermissionError:
                print(f"rm: {p}: permission denied")
                code = 1
            except Exception as e:
                print(f"rm: {p}: {e}")
                code = 1
        return code

    def _cmd_mv(self, args: List[str]) -> int:
        if len(args) < 2:
            print("Usage: mv src ... dest")
            return 2
        *srcs, dest = args
        dest_path = safe_expand(dest)
        try:
            if len(srcs) > 1:
                if not dest_path.exists() or not dest_path.is_dir():
                    print("mv: when moving multiple files, destination must be an existing directory")
                    return 1
                for s in srcs:
                    shutil.move(str(safe_expand(s)), str(dest_path))
            else:
                shutil.move(str(safe_expand(srcs[0])), str(dest_path))
            return 0
        except Exception as e:
            print(f"mv: {e}")
            return 1

    def _cmd_cp(self, args: List[str]) -> int:
        flags, rest = parse_flags(args, {"-r": "-r", "--recursive": "-r"})
        if len(rest) < 2:
            print("Usage: cp [-r] src ... dest")
            return 2
        *srcs, dest = rest
        dest_path = safe_expand(dest)
        try:
            if len(srcs) > 1:
                if not dest_path.exists() or not dest_path.is_dir():
                    print("cp: when copying multiple files, destination must be an existing directory")
                    return 1
                for s in srcs:
                    sp = safe_expand(s)
                    if sp.is_dir():
                        if "-r" in flags:
                            shutil.copytree(sp, dest_path / sp.name)
                        else:
                            print(f"cp: -r not specified; omitting directory '{sp}'")
                    else:
                        shutil.copy2(sp, dest_path / sp.name)
            else:
                sp = safe_expand(srcs[0])
                if sp.is_dir():
                    if "-r" in flags:
                        shutil.copytree(sp, dest_path)
                    else:
                        print(f"cp: -r not specified; omitting directory '{sp}'")
                        return 1
                else:
                    if dest_path.is_dir():
                        shutil.copy2(sp, dest_path / sp.name)
                    else:
                        # copying file → file
                        shutil.copy2(sp, dest_path)
            return 0
        except FileExistsError as e:
            print(f"cp: {e}")
            return 1
        except Exception as e:
            print(f"cp: {e}")
            return 1

    def _cmd_touch(self, args: List[str]) -> int:
        if not args:
            print("Usage: touch file ...")
            return 2
        code = 0
        for a in args:
            p = safe_expand(a)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.exists():
                    os.utime(p, None)
                else:
                    with p.open("a", encoding="utf-8"):
                        pass
            except Exception as e:
                print(f"touch: {p}: {e}")
                code = 1
        return code

    def _cmd_cat(self, args: List[str]) -> int:
        if not args:
            print("Usage: cat file ...")
            return 2
        code = 0
        for a in args:
            p = safe_expand(a)
            try:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    sys.stdout.write(f.read())
            except Exception as e:
                print(f"\ncat: {p}: {e}")
                code = 1
        return code

    def _cmd_clear(self, args: List[str]) -> int:
        cmd = "cls" if is_windows() else "clear"
        try:
            os.system(cmd)
        except Exception:
            pass
        return 0

    def _cmd_which(self, args: List[str]) -> int:
        if not args:
            print("Usage: which command")
            return 2
        cmd = args[0]
        path = shutil.which(cmd)
        if path:
            print(path)
            return 0
        print(f"{cmd} not found in PATH")
        return 1

    def _cmd_ai(self, args: List[str]) -> int:
        if not args:
            print('Usage: ai "instruction sentence..."')
            return 2
        sentence = " ".join(args)
        plan = self.translator.translate(sentence)
        if not plan:
            print("Could not parse instruction.")
            return 1
        print(f"Plan: {' ; '.join(' '.join(map(shlex.quote, p)) for p in plan)}")
        rc = 0
        for p in plan:
            line = " ".join(map(shlex.quote, p))
            rc = self.dispatch(line)
            if rc != 0:
                break
        return rc

    def _cmd_ps(self, args: List[str]) -> int:
        if psutil:
            try:
                # First quick call may return 0.0 cpu%; do a small warm-up
                for p in psutil.process_iter(attrs=["pid", "name"]):
                    pass
                time.sleep(0.05)
                procs = []
                for p in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_percent"]):
                    info = p.info
                    procs.append(info)
                procs.sort(key=lambda x: (x.get("cpu_percent") or 0.0), reverse=True)
                print(f"{'PID':>6}  {'CPU%':>6}  {'MEM%':>6}  NAME")
                for pr in procs[:200]:
                    print(f"{pr['pid']:>6}  {pr.get('cpu_percent', 0.0):>6.1f}  {pr.get('memory_percent', 0.0):>6.1f}  {pr.get('name','')}")
                return 0
            except Exception as e:
                print(f"ps: {e}")
                return 1
        # Fallback: system ps/tasklist
        try:
            if is_windows():
                subprocess.run(["tasklist"], check=False)
            else:
                subprocess.run(["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"], check=False)
            return 0
        except Exception as e:
            print(f"ps: {e}")
            return 1

    def _cmd_sysmon(self, args: List[str]) -> int:
        flags, rest = parse_flags(args, {"-w": "-w", "--watch": "-w"})
        watch = "-w" in flags
        interval = 1.0
        # allow optional numeric after -w
        if watch and rest:
            try:
                interval = float(rest[0])
            except Exception:
                pass

        if not psutil:
            print("sysmon: psutil not installed. Install with: pip install psutil")
            return 1

        try:
            while True:
                if not watch:
                    # Print once
                    self._print_sys_stats()
                    return 0
                else:
                    # Refreshing
                    self._print_sys_stats(clear=True)
                    time.sleep(interval)
        except KeyboardInterrupt:
            print()
            return 0
        except Exception as e:
            print(f"sysmon: {e}")
            return 1

    def _print_sys_stats(self, clear: bool = False) -> None:
        if clear:
            self._cmd_clear([])
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        load_avg = None
        try:
            if hasattr(os, "getloadavg"):
                load_avg = os.getloadavg()
        except Exception:
            load_avg = None

        print(f"{Fore.YELLOW}System Monitor{Style.RESET_ALL}")
        print(f"CPU: {cpu:.1f}%")
        print(f"Memory: {mem.percent:.1f}%  ({format_bytes(mem.used, True)}/{format_bytes(mem.total, True)})")
        print(f"Swap: {swap.percent:.1f}%  ({format_bytes(swap.used, True)}/{format_bytes(swap.total, True)})")
        if load_avg:
            print(f"Load avg (1,5,15): {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}")

    def _cmd_history(self, args: List[str]) -> int:
        n = 50
        if args:
            try:
                n = max(1, int(args[0]))
            except Exception:
                pass
        try:
            lines = []
            if self.history_path.exists():
                with self.history_path.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = [ln.rstrip("\n") for ln in f]
            start = max(0, len(lines) - n)
            for i in range(start, len(lines)):
                print(f"{i+1:>5}  {lines[i]}")
            return 0
        except Exception as e:
            print(f"history: {e}")
            return 1


# --------------------- Main --------------------------------------------------

def main() -> None:
    term = PyTerm()
    term.run()


if __name__ == "__main__":
    main()
