#!/usr/bin/env bash
SESSION="btc-daemon"

# Check if session already exists
tmux has-session -t $SESSION 2>/dev/null

if [ $? != 0 ]; then
  # Create new detached session and start the daemon
  tmux new-session -d -s $SESSION -c ~/projects/btc-alert-system "poetry run btc-alert"
  echo "BTC Alert Daemon started in tmux session '$SESSION'."
else
  echo "Session '$SESSION' is already running."
fi