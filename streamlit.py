#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyTerm Streamlit Web Interface
A web-based terminal interface using Streamlit for the PyTerm terminal emulator.

This file imports and uses the existing PyTerm implementation.
Make sure pyterm.py is in the same directory or Python path.
"""

import streamlit as st
import os
import sys
import time
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import List, Dict, Any
import importlib.util

# Try to import PyTerm from the main file
try:
    # First try direct import (if pyterm.py is in same directory)
    from pyterm import PyTerm, Command
    PYTERM_LOADED = True
except ImportError:
    try:
        # Alternative: try to load from a specific path
        spec = importlib.util.spec_from_file_location("pyterm", "./pyterm.py")
        pyterm_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pyterm_module)
        PyTerm = pyterm_module.PyTerm
        Command = pyterm_module.Command
        PYTERM_LOADED = True
    except Exception as e:
        PYTERM_LOADED = False
        IMPORT_ERROR = str(e)

# Custom CSS for terminal styling
TERMINAL_CSS = """
<style>
.terminal-container {
    background-color: #1a1a1a;
    color: #00ff41;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Courier New', monospace;
    padding: 20px;
    border-radius: 8px;
    max-height: 600px;
    overflow-y: auto;
    border: 2px solid #333;
    box-shadow: 0 0 20px rgba(0, 255, 65, 0.1);
}

.terminal-prompt {
    color: #00ff41;
    font-weight: bold;
}

.terminal-command {
    color: #ffffff;
    font-weight: normal;
}

.terminal-output {
    color: #e0e0e0;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 5px 0;
}

.terminal-error {
    color: #ff6b6b;
    background-color: rgba(255, 107, 107, 0.1);
    padding: 2px 4px;
    border-radius: 3px;
}

.terminal-info {
    color: #74c0fc;
}

.terminal-success {
    color: #51cf66;
}

.command-history {
    background-color: #2d2d2d;
    color: #cccccc;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Courier New', monospace;
    padding: 10px;
    border-radius: 4px;
    max-height: 200px;
    overflow-y: auto;
    font-size: 12px;
}

.status-bar {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 20px;
}

.quick-cmd-btn {
    margin: 2px;
}

.file-item {
    padding: 2px 0;
    font-size: 13px;
}

.stats-container {
    background-color: #f8f9fa;
    padding: 10px;
    border-radius: 6px;
    margin: 5px 0;
}
</style>
"""

class StreamlitPyTerm:
    """Streamlit wrapper for PyTerm terminal emulator."""
    
    def __init__(self):
        """Initialize the Streamlit PyTerm interface."""
        if not PYTERM_LOADED:
            st.error(f"❌ Could not load PyTerm module: {IMPORT_ERROR}")
            st.error("Please ensure pyterm.py is in the same directory as this file.")
            st.stop()
        
        self._init_session_state()
        self.pyterm = st.session_state.pyterm
    
    def _init_session_state(self):
        """Initialize all session state variables."""
        if 'pyterm' not in st.session_state:
            st.session_state.pyterm = PyTerm()
        
        if 'terminal_output' not in st.session_state:
            st.session_state.terminal_output = []
        
        if 'command_history' not in st.session_state:
            st.session_state.command_history = []
        
        if 'current_dir' not in st.session_state:
            st.session_state.current_dir = str(Path.cwd())
        
        if 'session_start_time' not in st.session_state:
            st.session_state.session_start_time = time.time()
    
    def capture_command_output(self, command: str) -> Dict[str, Any]:
        """Execute a command and capture its output and return code."""
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        result = {
            'command': command,
            'stdout': '',
            'stderr': '',
            'return_code': 0,
            'timestamp': time.strftime('%H:%M:%S'),
            'execution_time': 0
        }
        
        start_time = time.time()
        
        try:
            # Capture both stdout and stderr
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                result['return_code'] = self.pyterm.dispatch(command)
            
            result['stdout'] = stdout_buffer.getvalue()
            result['stderr'] = stderr_buffer.getvalue()
            
        except SystemExit:
            result['stdout'] = "🚪 Terminal session ended."
            result['return_code'] = 0
        except KeyboardInterrupt:
            result['stderr'] = "⚡ Command interrupted."
            result['return_code'] = 130
        except Exception as e:
            result['stderr'] = f"💥 Unexpected error: {str(e)}"
            result['return_code'] = 1
        
        result['execution_time'] = time.time() - start_time
        
        # Update current directory tracking
        st.session_state.current_dir = str(self.pyterm.cwd)
        
        return result
    
    def format_output_html(self, output: str, output_type: str = 'normal') -> str:
        """Format command output with appropriate styling."""
        if not output.strip():
            return ""
        
        # HTML escape the output
        import html
        escaped_output = html.escape(output)
        
        css_class_map = {
            'normal': 'terminal-output',
            'error': 'terminal-error',
            'info': 'terminal-info',
            'success': 'terminal-success'
        }
        
        css_class = css_class_map.get(output_type, 'terminal-output')
        return f'<div class="{css_class}">{escaped_output}</div>'
    
    def render_header(self):
        """Render the application header and status."""
        st.markdown("# 🖥️ PyTerm Web Terminal")
        
        # Status bar
        uptime = int(time.time() - st.session_state.session_start_time)
        status_html = f"""
        <div class="status-bar">
            <strong>Status:</strong> Connected | 
            <strong>Uptime:</strong> {uptime//60}m {uptime%60}s | 
            <strong>Commands:</strong> {len(st.session_state.command_history)} |
            <strong>Working Directory:</strong> {st.session_state.current_dir}
        </div>
        """
        st.markdown(status_html, unsafe_allow_html=True)
    
    def render_terminal_output(self):
        """Render the terminal output display."""
        st.markdown("### Terminal")
        
        # Control buttons
        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
        with col1:
            if st.button("🧹 Clear", key="clear_terminal", help="Clear terminal output"):
                st.session_state.terminal_output = []
                st.rerun()
        
        with col2:
            if st.button("🔄 Reset", key="reset_session", help="Reset entire session"):
                self._reset_session()
                st.rerun()
        
        with col3:
            auto_scroll = st.checkbox("📜 Auto-scroll", value=True)
        
        # Terminal display
        terminal_html = '<div class="terminal-container">'
        
        if not st.session_state.terminal_output:
            terminal_html += '<div class="terminal-info">Welcome to PyTerm Web Terminal! Type a command below to get started.</div>'
        
        for entry in st.session_state.terminal_output:
            # Command line
            prompt_html = f'<span class="terminal-prompt">{entry["prompt"]}</span>'
            command_html = f'<span class="terminal-command">{entry["command"]}</span>'
            terminal_html += f'<div>{prompt_html}{command_html}</div>'
            
            # Output
            if entry['stdout']:
                terminal_html += self.format_output_html(entry['stdout'], 'normal')
            if entry['stderr']:
                terminal_html += self.format_output_html(entry['stderr'], 'error')
            
            # Execution info
            if entry.get('execution_time', 0) > 0:
                exec_info = f"<small style='color: #888;'>[{entry['timestamp']} | {entry['execution_time']:.3f}s | exit: {entry['return_code']}]</small>"
                terminal_html += f'<div>{exec_info}</div>'
            
            terminal_html += '<br>'
        
        terminal_html += '</div>'
        
        if auto_scroll:
            # Add JavaScript for auto-scrolling
            terminal_html += """
            <script>
            setTimeout(function() {
                var container = document.querySelector('.terminal-container');
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            }, 100);
            </script>
            """
        
        st.markdown(terminal_html, unsafe_allow_html=True)
    
    def render_command_input(self):
        """Render command input interface."""
        st.markdown("---")
        
        # Quick action buttons
        st.markdown("**🚀 Quick Actions:**")
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        quick_commands = [
            ("📁 ls", "ls"),
            ("📍 pwd", "pwd"), 
            ("🏠 home", "cd ~"),
            ("⬆️ up", "cd .."),
            ("ℹ️ help", "help"),
            ("📊 status", "sysmon")
        ]
        
        for i, (label, cmd) in enumerate(quick_commands):
            with [col1, col2, col3, col4, col5, col6][i]:
                if st.button(label, key=f"quick_{i}", use_container_width=True):
                    self.execute_command(cmd)
        
        # Main command input
        st.markdown("**💻 Command Input:**")
        
        # Command input form
        with st.form("command_form", clear_on_submit=True):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                command = st.text_input(
                    "Standard Command:",
                    placeholder="Enter command (e.g., ls -la, mkdir test, rm file.txt)",
                    key="standard_command"
                )
            
            with col2:
                submit_cmd = st.form_submit_button("Execute", use_container_width=True)
        
        # AI/Natural language input
        with st.form("ai_form", clear_on_submit=True):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                ai_command = st.text_input(
                    "🤖 Natural Language (AI):",
                    placeholder="e.g., 'create a folder called project and go into it'",
                    key="ai_command"
                )
            
            with col2:
                submit_ai = st.form_submit_button("AI Execute", use_container_width=True)
        
        # Handle form submissions
        if submit_cmd and command.strip():
            self.execute_command(command.strip())
        
        if submit_ai and ai_command.strip():
            self.execute_command(f'ai "{ai_command.strip()}"')
    
    def execute_command(self, command: str):
        """Execute a command and update terminal state."""
        if not command.strip():
            return
        
        # Create terminal prompt
        current_path = Path(st.session_state.current_dir)
        if len(str(current_path)) > 50:
            display_path = f"...{str(current_path)[-47:]}"
        else:
            display_path = str(current_path)
        
        prompt = f"{display_path} $ "
        
        # Execute command
        result = self.capture_command_output(command)
        
        # Create terminal entry
        terminal_entry = {
            'prompt': prompt,
            'command': command,
            'stdout': result['stdout'],
            'stderr': result['stderr'],
            'return_code': result['return_code'],
            'timestamp': result['timestamp'],
            'execution_time': result['execution_time']
        }
        
        # Update session state
        st.session_state.terminal_output.append(terminal_entry)
        
        # Update command history (avoid duplicates)
        if command not in st.session_state.command_history:
            st.session_state.command_history.insert(0, command)
        else:
            # Move to front if it exists
            st.session_state.command_history.remove(command)
            st.session_state.command_history.insert(0, command)
        
        # Keep history manageable
        st.session_state.command_history = st.session_state.command_history[:100]
        
        # Rerun to update display
        st.rerun()
    
    def render_sidebar(self):
        """Render the sidebar with additional features."""
        with st.sidebar:
            st.markdown("## 📚 Command History")
            
            if st.session_state.command_history:
                # Show recent commands as clickable buttons
                st.markdown("**Recent Commands:**")
                for i, cmd in enumerate(st.session_state.command_history[:8]):
                    if st.button(f"▶️ {cmd[:30]}{'...' if len(cmd) > 30 else ''}", 
                               key=f"history_btn_{i}"):
                        self.execute_command(cmd)
                
                # Full history in expander
                with st.expander("📜 Full History"):
                    history_text = "\n".join([f"{i+1:3d}. {cmd}" 
                                            for i, cmd in enumerate(st.session_state.command_history)])
                    st.text_area("Commands", history_text, height=200, key="full_history")
            else:
                st.info("No commands executed yet.")
            
            st.markdown("---")
            
            # File browser
            self.render_file_browser()
            
            st.markdown("---")
            
            # System information
            self.render_system_info()
    
    def render_file_browser(self):
        """Render file browser in sidebar."""
        st.markdown("## 📁 File Browser")
        
        try:
            current_path = Path(st.session_state.current_dir)
            
            # Parent directory button
            if current_path.parent != current_path:
                if st.button("📁 .. (parent)", key="parent_dir"):
                    self.execute_command("cd ..")
            
            # List directories and files
            try:
                items = list(current_path.iterdir())
                dirs = [item for item in items if item.is_dir()][:10]
                files = [item for item in items if item.is_file()][:10]
                
                if dirs:
                    st.markdown("**📁 Directories:**")
                    for directory in sorted(dirs):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            if st.button(f"📁 {directory.name}", key=f"dir_{directory.name}"):
                                self.execute_command(f"cd '{directory.name}'")
                        with col2:
                            if st.button("📋", key=f"ls_dir_{directory.name}", help="List contents"):
                                self.execute_command(f"ls '{directory.name}'")
                
                if files:
                    st.markdown("**📄 Files:**")
                    for file in sorted(files)[:8]:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.text(f"📄 {file.name}")
                        with col2:
                            if st.button("👀", key=f"view_{file.name}", help="View file"):
                                self.execute_command(f"cat '{file.name}'")
                
                if len(items) > 20:
                    st.info(f"... and {len(items) - 20} more items")
                    
            except PermissionError:
                st.error("Permission denied reading directory")
            except Exception as e:
                st.error(f"Error: {e}")
                
        except Exception as e:
            st.error(f"File browser error: {e}")
    
    def render_system_info(self):
        """Render system information in sidebar."""
        st.markdown("## 🖥️ System Info")
        
        try:
            # Try to import psutil for system stats
            import psutil
            
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Display metrics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("CPU", f"{cpu_percent:.1f}%")
                st.metric("Memory", f"{memory.percent:.1f}%")
            with col2:
                st.metric("Disk", f"{disk.percent:.1f}%")
                st.metric("Processes", len(psutil.pids()))
            
        except ImportError:
            st.info("Install `psutil` for system monitoring:\n```\npip install psutil\n```")
        except Exception as e:
            st.error(f"System info error: {e}")
        
        # Session statistics
        st.markdown("**📊 Session Stats:**")
        session_uptime = int(time.time() - st.session_state.session_start_time)
        
        stats_data = {
            "Commands": len(st.session_state.command_history),
            "Terminal Lines": len(st.session_state.terminal_output),
            "Uptime": f"{session_uptime//60}m {session_uptime%60}s",
            "Current Dir": Path(st.session_state.current_dir).name
        }
        
        for key, value in stats_data.items():
            st.metric(key, value)
    
    def _reset_session(self):
        """Reset the entire terminal session."""
        st.session_state.pyterm = PyTerm()
        st.session_state.terminal_output = []
        st.session_state.command_history = []
        st.session_state.current_dir = str(Path.cwd())
        st.session_state.session_start_time = time.time()
    
    def run(self):
        """Main application runner."""
        # Apply custom CSS
        st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
        
        # Render components
        self.render_header()
        self.render_sidebar()
        self.render_terminal_output()
        self.render_command_input()
        
        # Footer
        st.markdown("---")
        st.markdown(
            """
            <div style='text-align: center; color: #666; padding: 20px;'>
                <p><strong>PyTerm Web Terminal</strong> - A powerful Python terminal emulator with web interface</p>
                <p>💡 Try the AI feature for natural language commands | 🔧 All standard terminal operations supported</p>
            </div>
            """, 
            unsafe_allow_html=True
        )


def main():
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="PyTerm Web Terminal",
        page_icon="🖥️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Create and run the terminal interface
    terminal = StreamlitPyTerm()
    terminal.run()


if __name__ == "__main__":
    main()
