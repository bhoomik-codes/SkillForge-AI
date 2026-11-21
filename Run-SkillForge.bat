
@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

where.exe node.exe >nul 2>&1
if errorlevel 1 goto missing_node
where.exe npm.cmd >nul 2>&1
if errorlevel 1 goto missing_node
where.exe uv.exe >nul 2>&1
if errorlevel 1 goto missing_uv

set "UV_PROJECT_ENVIRONMENT=%CD%\services\.venv-local"
set "UV_ENV_FILE="
set "UV_NO_ENV_FILE="
set "PYTHONUNBUFFERED=1"
echo Preparing SkillForge's Python environment...
if exist ".env" (
    if exist ".env.local" (
        uv.exe run --directory services --locked --no-dev --python 3.12 --env-file "%CD%\.env" --env-file "%CD%\.env.local" python -u "%CD%\scripts\run_local.py" %*
    ) else (
        uv.exe run --directory services --locked --no-dev --python 3.12 --env-file "%CD%\.env" python -u "%CD%\scripts\run_local.py" %*
    )
) else if exist ".env.local" (
    uv.exe run --directory services --locked --no-dev --python 3.12 --env-file "%CD%\.env.local" python -u "%CD%\scripts\run_local.py" %*
) else (
    uv.exe run --directory services --locked --no-dev --python 3.12 --no-env-file python -u "%CD%\scripts\run_local.py" %*
)
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" goto failed
goto done

:missing_node
echo Node.js and npm are required. Install Node.js 22.12 or newer and reopen this terminal.
set "RESULT=1"
goto failed

:missing_uv
echo uv is required. Install uv, add it to PATH, and reopen this terminal.
set "RESULT=1"

:failed
echo.
echo SkillForge could not finish. Review the error above.
if "%~1"=="" pause

:done
popd
exit /b %RESULT%
