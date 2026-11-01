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

set "PY_FILE="
set "PY_FLAGS="
if "%SCRIPT%"=="session-start" set "PY_FILE=session_start.py"
if "%SCRIPT%"=="pre-tool-use"  set "PY_FILE=pre_tool_use.py"
if "%SCRIPT%"=="pre-tool-use"  set "PY_FLAGS=-S"
if "%SCRIPT%"=="stop"          set "PY_FILE=stop.py"

if "%PY_FILE%"=="" (
    echo run-hook.cmd: unknown script %SCRIPT% >&2
    exit /b 1
)

python %PY_FLAGS% "%HOOK_DIR%%PY_FILE%"
exit /b %ERRORLEVEL%
CMDBLOCK

# Unix: run python directly. No subshells: pre-tool-use runs before every tool
# call, and -S skips site-packages (the hooks use the standard library only).
case "$0" in */*) SCRIPT_DIR="${0%/*}" ;; *) SCRIPT_DIR="." ;; esac
case "$1" in
  session-start) exec python3 "${SCRIPT_DIR}/session_start.py" ;;
  pre-tool-use)  exec python3 -S "${SCRIPT_DIR}/pre_tool_use.py" ;;
  stop)          exec python3 "${SCRIPT_DIR}/stop.py" ;;
  *) echo "run-hook.cmd: unknown script $1" >&2; exit 1 ;;
esac
