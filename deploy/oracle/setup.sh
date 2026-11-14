#!/usr/bin/env bash
# AI QUANT server on an always-free Oracle Cloud VM (Ubuntu 22.04/24.04, ARM Ampere or AMD micro).
# Always on (no sleeping like Render free), HTTPS via Caddy + a free sslip.io hostname, auto-restart, auto-update.
# Run as the default "ubuntu" user:   bash setup.sh
set -euo pipefail

read -rp "Twelve Data API key: " TD_KEY
read -rp "GOLDQUANT_TOKEN (a long random secret, same as in the app): " APP_TOKEN
read -rp "Data repository (e.g. derbalali76-web/gold-ai-quant): " DATA_REPO
read -rp "GitHub fine-grained token (read-only Contents on that repo): " REPO_TOKEN

IP=$(curl -fsS https://api.ipify.org)
HOST="${IP//./-}.sslip.io"
echo "Public hostname: https://$HOST"

sudo apt-get update -y
sudo apt-get install -y docker.io git debian-keyring debian-archive-keyring apt-transport-https curl
sudo systemctl enable --now docker

# Caddy (automatic Let's Encrypt certificate)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -y && sudo apt-get install -y caddy
echo "$HOST {
  reverse_proxy 127.0.0.1:10000
}" | sudo tee /etc/caddy/Caddyfile
sudo systemctl restart caddy

# Ubuntu images on Oracle block ports with iptables: open 80/443 (also add an Ingress rule in the VCN security list)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || sudo sh -c 'iptables-save > /etc/iptables/rules.v4' || true

# App code + container
sudo mkdir -p /opt/aiquant && sudo chown "$USER" /opt/aiquant
git clone --depth 1 "https://x-access-token:${REPO_TOKEN}@github.com/${DATA_REPO}.git" /opt/aiquant/src
cat > /opt/aiquant/env <<ENV
TWELVEDATA_API_KEY=$TD_KEY
GOLDQUANT_TOKEN=$APP_TOKEN
GOLDQUANT_DATA_REPO=$DATA_REPO
GOLDQUANT_REPO_TOKEN=$REPO_TOKEN
PORT=10000
ENV
chmod 600 /opt/aiquant/env
cp /opt/aiquant/src/deploy/oracle/update.sh /opt/aiquant/update.sh && chmod +x /opt/aiquant/update.sh
/opt/aiquant/update.sh

# Auto-update every 30 minutes (rebuilds only when the code changed)
( crontab -l 2>/dev/null | grep -v aiquant/update.sh; echo "*/30 * * * * /opt/aiquant/update.sh >> /opt/aiquant/update.log 2>&1" ) | crontab -
echo
echo "Done. In the app settings, set the server URL to: https://$HOST"
echo "Check: curl https://$HOST/health"
