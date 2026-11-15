@echo off
REM Starts the local PostgreSQL 18 server
"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" start -D "C:\Program Files\PostgreSQL\18\data" -l "%~dp0pg_server.log" -w
echo.
echo PostgreSQL started (port 5432).
echo Keep this window open (you can minimise it). Closing it stops PostgreSQL.
pause