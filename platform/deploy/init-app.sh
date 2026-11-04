#!/bin/sh
set -eu

# Only runs when PostgreSQL initializes an empty volume. The app owns its
# database but cannot create roles/databases or bypass database permissions.
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_user PGUSER
\getenv app_password PGPASSWORD
\getenv app_database PGDATABASE
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE :"app_database" OWNER :"app_user";
SQL
