: << 'CMDBLOCK'
@echo off
REM Cross-platform polyglot wrapper.
REM On Windows: cmd.exe runs the batch portion below.
REM On Unix:    the shell skips the batch block and runs the case statement.

if "%~1"=="" (
    echo run-hook.cmd: missing script name >&2
    exit /b 1
)

set "HOOK_DIR=%~dp0"
set "SCRIPT=%~1"

if "%SCRIPT%"=="session-start" set "PY_FILE=session_start.py"
if "%SCRIPT%"=="stop"          set "PY_FILE=stop.py"

if "%PY_FILE%"=="" (
    echo run-hook.cmd: unknown script %SCRIPT% >&2
    exit /b 1
)

python "%HOOK_DIR%%PY_FILE%"
exit /b %ERRORLEVEL%
CMDBLOCK

# Unix: run python directly
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
case "$1" in
  session-start) python3 "${SCRIPT_DIR}/session_start.py" ;;
  stop)          python3 "${SCRIPT_DIR}/stop.py" ;;
  *) echo "run-hook.cmd: unknown script $1" >&2; exit 1 ;;
esac
