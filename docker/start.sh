#!/bin/sh
# Starts PHP-FPM and Nginx in one process group. Used by the Dockerfile and by the Procfile.
#   APP_DIR   the project root (the parent of this docker/ directory). Detected automatically.
#   PORT      port Nginx listens on (default 8080).
set -e

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8080}"
CONF="/tmp/farmedia-nginx.conf"
mkdir -p /tmp/farmedia-client-body /tmp/farmedia-fastcgi

# Fill in the port, the real document root and the path of the security-header snippet.
sed -e "s#__PORT__#${PORT}#" \
    -e "s#/var/www/farmedia#${APP_DIR}#g" \
    -e "s#/etc/nginx/farmedia-security-headers.conf#${APP_DIR}/docker/security-headers.conf#g" \
    "$APP_DIR/docker/nginx.conf" > "$CONF"

php-fpm -D
exec nginx -g 'daemon off;' -c "$CONF"
