#!/bin/bash

# Path to the Python script
SCRIPT_PATH="/home/ec2-user/umotc/Telegram_bot/main.py"
# Path to the Python interpreter
PYTHON_PATH="/usr/bin/python3"  # Adjust if your Python interpreter is in a different location
# Process name or command to identify if the script is running
PROCESS_NAME="main.py"

#### Log treatment
# Variables
LOG_DIR="/var/log"
LOG_FILE="check_and_run.log"
HISTORY_COUNT=4
# Full path to the log file
LOG_PATH="$LOG_DIR/$LOG_FILE"

# Get yesterday's date in format DDMMYYYY
YESTERDAY=$(date -d "yesterday" +"%d%m%Y")

# Check if the log file exists
if [ -f "$LOG_PATH" ]; then
    # Rename the log file with yesterday's date
    sudo mv "$LOG_PATH" "$LOG_DIR/check_and_run.$YESTERDAY.log"
    echo "Log file renamed to: check_and_run.$YESTERDAY.log"
else
    echo "Log file $LOG_FILE does not exist."
fi

sudo touch "$LOG_PATH"
sudo chown ec2-user:ec2-user "$LOG_PATH" 
echo "New log file $LOG_FILE created"

# Remove log files older than 4 days
LOGS_TO_DELETE=$(ls -t $LOG_DIR/check_and_run.*.log | tail -n +$(($HISTORY_COUNT + 1)))

for log in $LOGS_TO_DELETE; do
    sudo rm -f "$log"
    echo "Deleted old log file: $log"
done

echo "About to start main process"

# Check if the script is running
if ! pgrep -f "$PROCESS_NAME" > /dev/null; then
    echo "$(date): Starting $SCRIPT_PATH" >> $LOG_PATH
    $PYTHON_PATH $SCRIPT_PATH >> $LOG_PATH 2>&1 &
else
    echo "$(date): $SCRIPT_PATH is already running" >> $LOG_PATH
fi
