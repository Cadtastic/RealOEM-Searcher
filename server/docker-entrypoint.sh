#!/bin/sh
# Fly mounts the volume at /data owned by root. Give it to the app user (files an earlier run or
# a root shell left behind included), then run the server as that user, never as root.
set -eu
mkdir -p /data/cache /data/data
chown -R app:app /data
exec setpriv --reuid=app --regid=app --init-groups -- "$@"
