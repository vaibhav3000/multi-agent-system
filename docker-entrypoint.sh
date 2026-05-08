#!/bin/sh
set -e

python -m app.core.migration_bootstrap
alembic upgrade head
exec "$@"
