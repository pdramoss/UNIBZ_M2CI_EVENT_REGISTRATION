#!/usr/bin/env bash

check_even_or_odd() {
    local number="$1"

    if [ "$((number % 2))" -eq 0 ]; then
        echo "$number is even."
    else
        echo "$number is odd."
    fi
}

check_even_or_odd 4
check_even_or_odd 7
check_even_or_odd 0
check_even_or_odd -3
