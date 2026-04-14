#!/bin/bash
PYTHON=$1
TEST_DIR=$2
RESULT_FILE=$3
IGNORE_FILES=$4
TIMEOUT_SECS=${5:-120}

echo "=== CinderX Functional Test Results ===" > $RESULT_FILE
echo "Date: $(date)" >> $RESULT_FILE
echo "Python: $($PYTHON --version 2>&1)" >> $RESULT_FILE
echo "TestDir: $TEST_DIR" >> $RESULT_FILE
echo "Timeout: ${TIMEOUT_SECS}s per file" >> $RESULT_FILE
echo "" >> $RESULT_FILE

TOTAL_CRASH=0
CRASHED_FILES=""

should_ignore() {
    local f=$(basename "$1")
    echo "$IGNORE_FILES" | tr ' ' '\n' | grep -qx "$f"
}

while IFS= read -r testfile; do
    if should_ignore "$testfile"; then
        echo "--- SKIP (known crash): $testfile ---" >> $RESULT_FILE
        echo "  Reason: Known to cause segfault/abort" >> $RESULT_FILE
        echo "" >> $RESULT_FILE
        TOTAL_CRASH=$((TOTAL_CRASH + 1))
        CRASHED_FILES="$CRASHED_FILES $testfile"
        continue
    fi

    echo "--- Running: $testfile ---" >> $RESULT_FILE
    timeout $TIMEOUT_SECS $PYTHON -m pytest "$testfile" -v --tb=short 2>&1 >> $RESULT_FILE
    exit_code=$?

    if [ $exit_code -eq 139 ] || [ $exit_code -eq 134 ]; then
        echo "  *** CRASH (exit code $exit_code): Segfault/Abort ***" >> $RESULT_FILE
        TOTAL_CRASH=$((TOTAL_CRASH + 1))
        CRASHED_FILES="$CRASHED_FILES $testfile"
    elif [ $exit_code -eq 124 ]; then
        echo "  *** TIMEOUT after ${TIMEOUT_SECS}s ***" >> $RESULT_FILE
    fi

    echo "" >> $RESULT_FILE
done < <(find $TEST_DIR -name "test*.py" -type f | sort)

echo "" >> $RESULT_FILE
echo "=== SUMMARY ===" >> $RESULT_FILE
echo "PASSED:  $(grep -c 'PASSED' $RESULT_FILE 2>/dev/null || echo 0)" >> $RESULT_FILE
echo "FAILED:  $(grep -c 'FAILED' $RESULT_FILE 2>/dev/null || echo 0)" >> $RESULT_FILE
echo "SKIPPED: $(grep -c 'SKIPPED' $RESULT_FILE 2>/dev/null || echo 0)" >> $RESULT_FILE
echo "XFAILED: $(grep -c 'XFAIL' $RESULT_FILE 2>/dev/null || echo 0)" >> $RESULT_FILE
echo "CRASHED FILES: $TOTAL_CRASH" >> $RESULT_FILE
if [ -n "$CRASHED_FILES" ]; then
    echo "Crashed files:$CRASHED_FILES" >> $RESULT_FILE
fi

echo "DONE"
