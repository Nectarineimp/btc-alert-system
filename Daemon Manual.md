#tmux Commands

**Launch / Background Daemon**: ./run_daemon.sh

**Attach to live Dashboard**: tmux attach -t btc-daemon

**Detach from Dashboard** (leave running): Press Ctrl + B, then release and press D.

**Terminate Daemon**: Attach and press Ctrl + C, **or run** tmux kill-session -t btc-daemon.