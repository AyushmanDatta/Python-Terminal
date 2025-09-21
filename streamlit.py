# streamlit_app.py
import streamlit as st
import io, contextlib, os, tempfile, uuid, shutil
from pathlib import Path

# IMPORTANT: your attached snippet should be saved as pyterm.py in the same folder
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

    # Instantiate PyTerm (do not call run())
    term = PyTerm()
    term.cwd = base_dir.resolve()  # start inside sandbox
    st.session_state.term = term

    # Console buffer [(label, text), ...]
    st.session_state.console = []

    # By default, do not auto-confirm destructive prompts
    st.session_state.auto_confirm = False
    st.session_state.strict_sandbox = False  # flip to True to enforce path jail

    # Patch confirm() so interactive prompts don’t block Streamlit
    def confirm_stub(prompt: str) -> bool:
        # Use the checkbox as the policy for confirmations (e.g., rm without -f)
        return bool(st.session_state.get('auto_confirm', False))
    pyterm_mod.confirm = confirm_stub

    # Optional: Strictly sandbox path expansions to base_dir only
    # This prevents absolute paths from escaping the sandbox root.
    def safe_expand_sandboxed(path: str) -> Path:
        # Defer strictness to UI checkbox
        if not st.session_state.get('strict_sandbox', False):
            return pyterm_mod.safe_expand(path)  # fall back to original behavior

        # When strict sandbox is ON:
        raw = os.path.expandvars(os.path.expanduser(path))
        p = Path(raw)

        # If absolute, strip root to make it relative, else keep relative
        if p.is_absolute():
            # Convert "/etc/passwd" -> "etc/passwd"
            p = Path(str(p).lstrip(os.sep))

        target = (st.session_state.base_dir / p).resolve()

        # Disallow directory traversal outside base_dir
        base_resolved = st.session_state.base_dir.resolve()
        if not str(target).startswith(str(base_resolved)):
            return base_resolved
        return target

    # Replace module-level safe_expand (PyTerm uses it everywhere)
    pyterm_mod.safe_expand = safe_expand_sandboxed

init_session()
term = st.session_state.term

st.title("PyTerm (Streamlit)")
st.write("Type shell-like commands (pwd, ls, cd, mkdir, rm, mv, cp, touch, cat, which, history).")
st.write("Natural language via: ai \"create folder test and list\"")

# Controls
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
    cmd = st.text_input("Command", placeholder="ls -l  |  ai \"create folder demo and list\"")
    submitted = st.form_submit_button("Run")
    if submitted and cmd.strip():
        # Special-case clear to wipe UI console
        if cmd.strip() in ("clear", "cls"):
            st.session_state.console = []
        else:
            buf_out, buf_err = io.StringIO(), io.StringIO()
            try:
                # Keep process cwd in sync before dispatch (as in PyTerm.run)
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
                    text = f"[exit code {locals().get('rc', 0)}]"
                st.session_state.console.append((f"$ {cmd}", text))

                # Append to history file (like PyTerm.run)
                try:
                    term.history_path.parent.mkdir(parents=True, exist_ok=True)
                    with term.history_path.open("a", encoding="utf-8") as f:
                        f.write(cmd + "\n")
                except Exception:
                    pass

# Render console
for label, text in st.session_state.console[-300:]:
    st.markdown(f"**{label}**")
    st.code(text.rstrip(), language="")

# Quick viewer of last 20 history lines
with st.expander("History (last 20)"):
    try:
        lines = []
        if term.history_path.exists():
            lines = term.history_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max(0, len(lines) - 20)
        for i, line in enumerate(lines[start:], start=start + 1):
            st.text(f"{i:>5}  {line}")
    except Exception as e:
        st.text(f"[history error] {e}")
