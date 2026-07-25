#!/usr/bin/env bash
# One-command deploy for Ubuntu + Caddy. Run ON the server, from inside a clone:
#
#   sudo DOMAIN=toeic.example.com GROQ_API_KEY=gsk_... ./deploy.sh
#
# Re-run any time (git pull first) to update — it is idempotent.
# DOMAIN may be a bare IP; then the site is served over plain HTTP (no TLS).
# ponytail: no rsync/registry/blue-green. The clone you run this from IS the
# deploy; update path is `git pull && sudo systemctl restart $SERVICE`.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="${SERVICE:-toeic-cut}"
PORT="${PORT:-8001}"
RUN_USER="${RUN_USER:-${SUDO_USER:-root}}"
CADDY_MAIN="/etc/caddy/Caddyfile"
CADDY_SITE="/etc/caddy/conf.d/${SERVICE}.caddy"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run with sudo"
[[ -f "$APP_DIR/server/app.py" ]] || die "$APP_DIR is not the project root"
[[ -n "${DOMAIN:-}" ]] || die "set DOMAIN=your.domain (or the server IP)"

# --- packages ---------------------------------------------------------------
echo "==> apt"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip ffmpeg >/dev/null
command -v caddy >/dev/null || die "caddy not installed"

# --- venv + deps ------------------------------------------------------------
echo "==> venv"
[[ -d "$APP_DIR/.venv" ]] || sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/.venv"
# No faster-whisper to skip any more: Groq is the only backend, so the whole
# requirements.txt fits a 2GB box (~150MB RSS per worker).
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# --- .env -------------------------------------------------------------------
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "==> .env from .env.example"
  install -o "$RUN_USER" -m 600 "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
if [[ -n "${GROQ_API_KEY:-}" ]]; then
  sed -i "s|^GROQ_API_KEY=.*|GROQ_API_KEY=${GROQ_API_KEY}|" "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
grep -q '^GROQ_API_KEY=.\+' "$APP_DIR/.env" \
  || die "GROQ_API_KEY empty in $APP_DIR/.env (config.py refuses to start without it)"

# --- systemd ----------------------------------------------------------------
echo "==> systemd unit $SERVICE"
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=TOEIC audio auto cut
After=network-online.target

[Service]
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q "$SERVICE"
systemctl restart "$SERVICE"

# --- caddy ------------------------------------------------------------------
echo "==> caddy site $DOMAIN"
mkdir -p /etc/caddy/conf.d
SITE="$DOMAIN"
[[ "$DOMAIN" =~ ^[0-9.]+$ ]] && SITE="http://$DOMAIN"   # bare IP: no TLS possible
MAX_MB=$(( $(grep -oP '^MAX_UPLOAD_MB=\K[0-9]+' "$APP_DIR/.env" || echo 50) + 10 ))
cat > "$CADDY_SITE" <<EOF
${SITE} {
	request_body {
		max_size ${MAX_MB}MB
	}
	reverse_proxy 127.0.0.1:${PORT}
}
EOF
# Own file under conf.d so the existing Caddyfile keeps its own site blocks.
if ! grep -q 'import /etc/caddy/conf.d/' "$CADDY_MAIN"; then
  cp "$CADDY_MAIN" "${CADDY_MAIN}.bak.$(date +%s)"
  printf '\nimport /etc/caddy/conf.d/*.caddy\n' >> "$CADDY_MAIN"
fi
caddy validate --config "$CADDY_MAIN" >/dev/null 2>&1 \
  || die "caddy validate failed; restore ${CADDY_MAIN}.bak.* and check $CADDY_SITE"
systemctl reload caddy

# --- check: fails loudly (with logs) if the app didn't actually come up -----
echo "==> health"
code=""
for _ in $(seq 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/" || true)
  [[ "$code" == "200" ]] && break
  sleep 1
done
[[ "$code" == "200" ]] || {
  journalctl -u "$SERVICE" -n 30 --no-pager
  die "app not responding on 127.0.0.1:${PORT}"
}
echo "OK -> ${SITE}   (logs: journalctl -u ${SERVICE} -f)"
