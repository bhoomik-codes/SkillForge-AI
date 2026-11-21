#!/bin/sh
set -eu

root=$(CDPATH= cd "$(dirname "$0")" && pwd -P)
cd "$root"

# Finder's Terminal environment may omit Homebrew and user-local installations.
PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin"
export PATH

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    printf '%s\n' 'Node.js and npm are required. Install Node.js 22.12 or newer and reopen Terminal.' >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'uv is required. Install uv and reopen Terminal.' >&2
    exit 1
fi

UV_PROJECT_ENVIRONMENT="$root/services/.venv-local"
PYTHONUNBUFFERED=1
export UV_PROJECT_ENVIRONMENT PYTHONUNBUFFERED
unset UV_ENV_FILE UV_NO_ENV_FILE

printf '%s\n' "Preparing SkillForge's Python environment..."
if [ -f "$root/.env" ]; then
    if [ -f "$root/.env.local" ]; then
        exec uv run --directory services --locked --no-dev --python 3.12 \
            --env-file ../.env --env-file ../.env.local python -u "$root/scripts/run_local.py" "$@"
    fi
    exec uv run --directory services --locked --no-dev --python 3.12 \
        --env-file ../.env python -u "$root/scripts/run_local.py" "$@"
fi
if [ -f "$root/.env.local" ]; then
    exec uv run --directory services --locked --no-dev --python 3.12 \
        --env-file ../.env.local python -u "$root/scripts/run_local.py" "$@"
fi
exec uv run --directory services --locked --no-dev --python 3.12 \
    --no-env-file python -u "$root/scripts/run_local.py" "$@"
