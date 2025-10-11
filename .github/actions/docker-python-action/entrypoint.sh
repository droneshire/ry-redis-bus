#!/bin/bash
set -e

echo "Entrypoint version: $1"

# Handle externally managed environment (Python 3.11+)
# First try with force-reinstall, then fallback to break-system-packages if needed
if ! pip install --upgrade --force-reinstall --no-deps pip pip-tools 2>/dev/null; then
    echo "Using --break-system-packages due to externally managed environment..."
    pip install --upgrade --break-system-packages pip pip-tools || true
fi

# Install uv with appropriate flags
if ! pip install --force-reinstall --no-deps uv 2>/dev/null; then
    echo "Installing uv with --break-system-packages..."
    pip install --break-system-packages uv
fi

uv pip compile --strip-extras --output-file=requirements.txt packages/base_requirements.in packages/dev_requirements.in
uv pip install --system --break-system-packages -r requirements.txt

# Lint with black
make check_format PYTHON=python3

# Lint with mypy
make mypy PYTHON=python3

# Lint with pylint
make pylint PYTHON=python3

# Test with pytest
make test PYTHON=python3

# If you need to keep the container running (for services etc.), uncomment the next line
# tail -f /dev/null
RESULT="🍻🍻🍻 Passed!"

if [[ -n "$GITHUB_OUTPUT" ]]; then
    echo "result=$RESULT" >> "$GITHUB_OUTPUT"
fi

# if there's a .coverage file, echo the result of the coverage report to the output
if [[ -f .coverage ]]; then
    COVERAGE_REPORT=$(coverage report)
    echo $(coverage report)
    # get the percentage from the coverage report
    COVERAGE_PERCENT=$(echo $COVERAGE_REPORT | grep -oP 'TOTAL.*\d+\%' | grep -oP '\d+\%')
    echo "coverage_percentage=$COVERAGE_PERCENT" >> "$GITHUB_OUTPUT"
fi
