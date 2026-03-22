#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${DOMAIN:-yourdomain.com}"
APP_DIR="/var/www/taskflow"
REPO_URL="${REPO_URL:-}"
PYTHON="${PYTHON:-python3.11}"

echo "═══════════════════════════════════════"
echo "  TaskFlow Deploy — $(date '+%F %T')"
echo "═══════════════════════════════════════"

apt-get update -q
apt-get install -y -q \
    python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib \
    nginx redis-server \
    certbot python3-certbot-nginx

systemctl enable redis-server && systemctl start redis-server
echo "→ Redis: $(systemctl is-active redis-server)"

mkdir -p "$APP_DIR" /var/log/taskflow /var/run/celery
chown -R www-data:www-data /var/log/taskflow /var/run/celery

if [ -n "$REPO_URL" ]; then
    if [ -d "$APP_DIR/.git" ]; then
        cd "$APP_DIR" && git pull
    else
        git clone "$REPO_URL" "$APP_DIR"
    fi
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo "✗ ERROR: $APP_DIR/.env not found. Copy .env.example → .env and fill values."
    exit 1
fi

echo "→ Installing Python dependencies…"
$PYTHON -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

cd "$APP_DIR/backend"
echo "→ Running migrations…"
"$APP_DIR/venv/bin/python" manage.py migrate --no-input
echo "→ Collecting static files…"
"$APP_DIR/venv/bin/python" manage.py collectstatic --no-input --clear

cp "$APP_DIR/gunicorn.conf.py"            /var/www/taskflow/gunicorn.conf.py
cp "$APP_DIR/taskflow.service"            /etc/systemd/system/taskflow.service
cp "$APP_DIR/taskflow-celery.service"     /etc/systemd/system/taskflow-celery.service
cp "$APP_DIR/taskflow-celerybeat.service" /etc/systemd/system/taskflow-celerybeat.service

systemctl daemon-reload
for svc in taskflow taskflow-celery taskflow-celerybeat; do
    systemctl enable "$svc" && systemctl restart "$svc"
    echo "→ $svc: $(systemctl is-active $svc)"
done

cp "$APP_DIR/nginx/taskflow.conf" /etc/nginx/sites-available/taskflow
ln -sf /etc/nginx/sites-available/taskflow /etc/nginx/sites-enabled/taskflow
nginx -t && systemctl reload nginx
echo "→ Nginx reloaded"

if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" \
        --non-interactive --agree-tos -m "admin@$DOMAIN" --redirect
else
    certbot renew --quiet
fi

echo ""
echo "✓ Deploy complete — https://$DOMAIN"
for svc in taskflow taskflow-celery taskflow-celerybeat redis-server nginx; do
    printf "  %-30s %s\n" "$svc" "$(systemctl is-active $svc)"
done
