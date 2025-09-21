# streamlit_app.py
import streamlit as st
import io, contextlib, os, tempfile, uuid, shutil
from pathlib import Path

# Import your terminal from main.py
import main as pyterm_mod
from main import PyTerm

def init_session():
    if 'initialized' in st.session_state:
        return
    st.session_state.initialized = True

    # Per-session sandbox directory
    st.session_state.session_id = str(uuid.uuid4())[:8]
    base_dir = Path(tempfile.gettempdir()) / f"pyterm_sandbox_{st.session_state.session_id}"
    base_dir.mkdir(parents=True, exist_ok=True)
    st.session_state.base_dir = base_dir

    # Instantiate your terminal (do NOT call run())
    term = PyTerm()
    term.cwd = base_dir.resolve()
    st.session_state.term = term

    # UI console buffer
    st.session_state.console = []

    # Controls
    st.session_state.auto_confirm = False
    st.session_state.strict_sandbox = False  # flip ON to confine to sandbox

    # If your code has a confirm() helper, patch it so delete prompts don’t block
    def confirm_stub(prompt: str) -> bool:
        return bool(st.session_state.get('auto_confirm', False))
    if hasattr(pyterm_mod, "confirm"):
        pyterm_mod.confirm = confirm_stub

    # Optional: strictly sandbox safe_expand() if your code exposes it
    def _fallback_expand(path: str) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(path)))

    def _default_expand(path: str) -> Path:
        if hasattr(pyterm_mod, "safe_expand"):
            return pyterm_mod.safe_expand(path)
        return _fallback_expand(path)

    def safe_expand_sandboxed(path: str) -> Path:
        # When strict sandbox is OFF, use your normal expansion
        if not st.session_state.get('strict_sandbox', False):
            return _default_expand(path)

        # When strict sandbox is ON, force all paths under base_dir
        raw = os.path.expandvars(os.path.expanduser(path))
        p = Path(raw)
        if p.is_absolute():
            p = Path(str(p).lstrip(os.sep))  # strip leading "/" to keep inside sandbox
        target = (st.session_state.base_dir / p).resolve()
        base_resolved = st.session_state.base_dir.resolve()
        if not str(target).startswith(str(base_resolved)):
            return base_resolved
        return target

    if hasattr(pyterm_mod, "safe_expand"):
        pyterm_mod.safe_expand = safe_expand_sandboxed

init_session()
term = st.session_state.term

st.title("PyTerm (Streamlit)")
st.write("Enter commands like: pwd, ls, cd, mkdir, rm, mv, cp, touch, cat, which, history.")
st.write('Natural language (if your code supports it): ai "create folder demo and list"')

# Sidebar controls
with st.sidebar:
    st.header("Session")
    st.caption(f"Sandbox: {st.session_state.base_dir}")
    st.checkbox("Auto-confirm deletes (rm prompts)", key="auto_confirm", value=False)
    st.checkbox("Strict sandbox (confine all paths under sandbox)", key="strict_sandbox", value=False)
    if st.button("Clear console"):
        st.session_state.console = []
    if st.button("Reset sandbox"):
        try:
            shutil.rmtree(st.session_state.base_dir, ignore_errors=True)
        except Exception:
            pass
        st.session_state.base_dir.mkdir(parents=True, exist_ok=True)
        term.cwd = st.session_state.base_dir.resolve()
        st.session_state.console = []

st.caption(f"Current directory: {term.cwd}")

# Command form
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
                # Keep process cwd in sync (mirrors typical CLI behavior)
                os.chdir(term.cwd)
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

                # Append to history file if your class exposes it
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

# Quick history viewer
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
