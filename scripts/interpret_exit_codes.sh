#!/usr/bin/env bash

ls
success_exit_code=$?
echo "Successful command exit code: $success_exit_code"
if [ "$success_exit_code" -eq 0 ]; then
    echo "The command succeeded."
else
    echo "The command failed."
fi

ls /nonexistent
failure_exit_code=$?
echo "Failing command exit code: $failure_exit_code"
if [ "$failure_exit_code" -eq 0 ]; then
    echo "The command unexpectedly succeeded."
else
    echo "The command failed as expected."
fi
