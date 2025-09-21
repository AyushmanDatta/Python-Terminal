# streamlit_app.py
import io, contextlib, os, shutil, tempfile, uuid, sys
from pathlib import Path

# Important: don't name this file "streamlit.py" (it will shadow the package)
import streamlit as st

# Your terminal implementation lives in main.py
import main as pyterm_mod
from main import PyTerm

PROJECT_DIR = Path(__file__).parent.resolve()

def init_session():
    if "initialized" in st.session_state:
        return
    st.session_state.initialized = True

    # Create a per-session sandbox (optional; not default CWD)
    st.session_state.session_id = str(uuid.uuid4())[:8]
    sandbox = Path(tempfile.gettempdir()) / f"pyterm_sandbox_{st.session_state.session_id}"
    sandbox.mkdir(parents=True, exist_ok=True)
    st.session_state.sandbox = sandbox

    # Instantiate terminal (do NOT call run())
    term = PyTerm()
    term.cwd = PROJECT_DIR  # default to your project dir
    st.session_state.term = term

    # Console buffer for UI
    st.session_state.console = []

    # Controls
    st.session_state.auto_confirm = False
    st.session_state.strict_sandbox = False  # jail paths under sandbox when True

    # If your CLI uses a confirm() prompt (e.g., rm), patch it to respect a checkbox
    def confirm_stub(prompt: str) -> bool:
        return bool(st.session_state.get("auto_confirm", False))
    if hasattr(pyterm_mod, "confirm"):
        pyterm_mod.confirm = confirm_stub

    # Wrap safe_expand so, when strict sandbox is ON, all paths resolve inside sandbox
    def _fallback_expand(path: str) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(path))).resolve()

    def _default_expand(path: str) -> Path:
        if hasattr(pyterm_mod, "safe_expand"):
            return pyterm_mod.safe_expand(path)
        return _fallback_expand(path)

    def safe_expand_sandboxed(path: str) -> Path:
        if not st.session_state.get("strict_sandbox", False):
            return _default_expand(path)

        # Jail: force any path under sandbox
        raw = os.path.expandvars(os.path.expanduser(path))
        p = Path(raw)
        if p.is_absolute():
            p = Path(str(p).lstrip(os.sep))  # strip leading "/" to keep inside sandbox
        target = (st.session_state.sandbox / p).resolve()
        base = st.session_state.sandbox.resolve()
        if not str(target).startswith(str(base)):
            return base
        return target

    if hasattr(pyterm_mod, "safe_expand"):
        pyterm_mod.safe_expand = safe_expand_sandboxed

init_session()
term = st.session_state.term

st.title("PyTerm (Streamlit)")
st.caption(f"Project dir: {PROJECT_DIR}")
st.caption(f"Sandbox dir: {st.session_state.sandbox}")

# Sidebar controls
with st.sidebar:
    st.header("Session")
    st.radio(
        "Start / switch working directory",
        ["Project directory", "Sandbox"],
        key="cwd_choice",
        index=0,
    )
    if st.session_state.cwd_choice == "Project directory":
        term.cwd = PROJECT_DIR
    else:
        term.cwd = st.session_state.sandbox

    st.checkbox("Strict sandbox (jail all paths under sandbox)", key="strict_sandbox", value=False)
    st.checkbox("Auto-confirm deletes (rm prompts)", key="auto_confirm", value=False)

    # Seed sandbox with repo files (optional, for safe demos)
    if st.button("Seed sandbox with main.py and this app"):
        for name in ("main.py", "streamlit_app.py", "README.md"):
            src = PROJECT_DIR / name
            dst = st.session_state.sandbox / name
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    st.warning(f"Could not copy {name}: {e}")

    if st.button("Reset sandbox"):
        try:
            shutil.rmtree(st.session_state.sandbox, ignore_errors=True)
        except Exception:
            pass
        st.session_state.sandbox.mkdir(parents=True, exist_ok=True)

    if st.button("Clear console"):
        st.session_state.console = []

st.write("Use built-ins: help, pwd, ls, cd, mkdir, rm, mv, cp, touch, cat, which, history, ps, sysmon, ai.")

st.caption(f"Current directory: {term.cwd}")

# Command input
import io
with st.form("cmd_form", clear_on_submit=True):
    cmd = st.text_input("Command", placeholder='ls -l  |  ai "create folder demo and list"')
    submitted = st.form_submit_button("Run")
    if submitted and cmd.strip():
        if cmd.strip() in ("clear", "cls"):
            st.session_state.console = []
        else:
            buf_out, buf_err = io.StringIO(), io.StringIO()
            rc = 0
            try:
                os.chdir(term.cwd)  # keep process CWD in sync
                with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                    rc = term.dispatch(cmd)
            except SystemExit:
                st.session_state.console.append((f"$ {cmd}", "[session ended by 'exit']"))
            except Exception as e:
                st.session_state.console.append((f"$ {cmd}", f"Error: {e}"))
            finally:
                out = buf_out.getvalue()
                err = buf_err.getvalue()
                text = out + (("\n" + err) if err else "")
                if not text.strip():
                    text = f"[exit code {rc}]"
                st.session_state.console.append((f"$ {cmd}", text))
                # Append to history if available
                try:
                    if hasattr(term, "history_path"):
                        term.history_path.parent.mkdir(parents=True, exist_ok=True)
                        with term.history_path.open("a", encoding="utf-8") as f:
                            f.write(cmd + "\n")
                except Exception:
                    pass

# Render console
for label, text in st.session_state.console[-300:]:
    st.markdown(f"**{label}**")
    st.code(text.rstrip(), language="")

# History viewer
with st.expander("History (last 20)"):
    try:
        lines = []
        if hasattr(term, "history_path") and term.history_path.exists():
            lines = term.history_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max(0, len(lines) - 20)
        for i, line in enumerate(lines[start:], start=start + 1):
            st.text(f"{i:>5}  {line}")
    except Exception as e:
        st.text(f"[history error] {e}")
