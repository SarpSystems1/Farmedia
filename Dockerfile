# Production image: Nginx + PHP-FPM serving the Farmedia PHP app (document root php/public).
# Build:  docker build -t farmedia .
# Run:    docker run --env-file .env -p 8080:8080 farmedia
# The image does not contain .env (see .dockerignore): pass the settings with --env-file.
FROM php:8.3-fpm-alpine

# Nginx for HTTP. pdo_mysql for the database. curl (health check) and openssl (Claude, Open-Meteo,
# Overpass, Nominatim over HTTPS) are part of the base image or added here.
RUN apk add --no-cache nginx curl \
    && docker-php-ext-install pdo_mysql

COPY docker/php.ini /usr/local/etc/php/conf.d/farmedia.ini

WORKDIR /var/www/farmedia
COPY php ./php
COPY docker ./docker
RUN chmod +x docker/start.sh \
    && chown -R www-data:www-data php

ENV APP_ENV=production \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health.php" || exit 1

# Nginx starts as root on its port; PHP-FPM workers run as www-data.
CMD ["sh", "docker/start.sh"]
