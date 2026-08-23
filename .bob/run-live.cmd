@echo off
rem Launch the live measurement MCP server for IBM Bob, from any working directory.
rem
rem Same three reasons as run-evidence.cmd, plus one that is specific to this server:
rem it measures rather than reads, so it needs numpy, scipy, pillow, sgp4 and httpx.
rem The project venv is not a preference here, it is the only interpreter on a normal
rem checkout that has them.
rem
rem A missing venv is reported rather than worked around. The alternative, falling
rem through to a system interpreter, produces a server that answers initialize and
rem then fails every measurement on an import error, which inside Bob looks like a
rem broken product rather than a missing install step.

cd /d "%~dp0.."

if defined TRACETRIAGE_PYTHON (
  "%TRACETRIAGE_PYTHON%" -m pipeline.tracetriage.mcp_live
  exit /b %errorlevel%
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pipeline.tracetriage.mcp_live
  exit /b %errorlevel%
)

echo The live measurement server needs this project's virtual environment, which 1>&2
echo carries numpy, scipy, pillow, sgp4 and httpx. Create it with: 1>&2
echo   python -m venv .venv 1>&2
echo   .venv\Scripts\python.exe -m pip install -e . 1>&2
echo Or set TRACETRIAGE_PYTHON to an interpreter that already has them. 1>&2
exit /b 9009
