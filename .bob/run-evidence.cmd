@echo off
rem Launch the evidence MCP server for IBM Bob, from any working directory.
rem
rem Why a launcher rather than a bare command in mcp.json. Three reasons, each one a
rem way the demo failed before this file existed.
rem
rem 1. The working directory. Bob's MCP config takes a cwd, and this server resolves
rem    its evidence relative to the repository root. Rather than depend on the host
rem    honouring that field, this script moves to the root itself: %~dp0 is .bob\, so
rem    the parent is the repository. A judge who opens Bob from a subfolder still gets
rem    a server that finds apps\web\public\data.
rem
rem 2. Which interpreter. On Windows, bare "python" can resolve to the Microsoft Store
rem    alias, a stub that opens the Store and exits. That failure surfaces inside Bob
rem    as a server with no tools, which reads as "this project's MCP does not work".
rem    The project venv is preferred because it is the interpreter every test here ran
rem    under; py -3 is the documented Windows launcher; bare python is the last resort.
rem
rem 3. A missing interpreter must say so. Falling through to nothing would leave Bob
rem    holding a server that never answers initialize.
rem
rem This server imports only the standard library, so any Python 3.11 or newer answers
rem it. tests/test_mcp_server.py checks that claim by running it with site-packages and
rem the ambient environment switched off.

cd /d "%~dp0.."

if defined TRACETRIAGE_PYTHON (
  "%TRACETRIAGE_PYTHON%" scripts\mcp_server.py
  exit /b %errorlevel%
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\mcp_server.py
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\mcp_server.py
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python scripts\mcp_server.py
  exit /b %errorlevel%
)

echo No Python interpreter was found. Install Python 3.11 or newer, or set 1>&2
echo TRACETRIAGE_PYTHON to the interpreter to use. This server needs only the 1>&2
echo standard library. 1>&2
exit /b 9009
