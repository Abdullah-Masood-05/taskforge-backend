#!/usr/bin/env bash
# Render build script — runs every deploy before the start command.
set -o errexit

pip install --upgrade pip
pip install -r requirements/prod.txt

python manage.py collectstatic --no-input
python manage.py migrate
