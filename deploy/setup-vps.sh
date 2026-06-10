#!/bin/bash
# ============================================================================
# VPS Setup Script for algotradeai.net
# ============================================================================
# Run this on your VPS after creating it and connecting via SSH as root
# Usage: bash setup-vps.sh
# ============================================================================

set -e  # Exit immediately if a command fails

echo "=============================================="
echo "  AI Trading Bot - VPS Setup"
echo "  Domain: algotradeai.net"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Configuration (CHANGE THESE) ---
DOMAIN="api.algotradeai.net"
ADMIN_USER="garad"
ADMIN_EMAIL="agarad60@gmail.com"
ADMIN_PASSWORD="ChangeThisStrongPassword123!"
SECRET_KEY="$(openssl rand -hex 32)"

# --- Step 1: Update System ---
echo -e "${YELLOW}[1/10] Updating system packages...${NC}"
apt update && apt upgrade -y

# --- Step 2: Install Dependencies ---
echo -e "${YELLOW}[2/10] Installing Python, Nginx, Git, UFW...${NC}"
apt install -y python3 python3-pip python3-venv nginx git ufw certbot python3-certbot-nginx

# --- Step 3: Create Directories ---
echo -e "${YELLOW}[3/10] Creating project directories...${NC}"
mkdir -p /opt/mt5-bot/backend
mkdir -p /opt/mt5-bot/logs

# --- Step 4: Check if backend files exist ---
if [ ! -f "/opt/mt5-bot/backend/main.py" ]; then
    echo -e "${RED}ERROR: Backend files not found in /opt/mt5-bot/backend/${NC}"
    echo -e "${RED}Please copy your backend folder first:${NC}"
    echo -e "${RED}  scp -r backend/ root@YOUR_VPS_IP:/opt/mt5-bot/${NC}"
    exit 1
fi

# --- Step 5: Set Up Python Environment ---
echo -e "${YELLOW}[5/10] Setting up Python virtual environment...${NC}"
cd /opt/mt5-bot/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# --- Step 6: Create .env file ---
echo -e "${YELLOW}[6/10] Creating environment configuration...${NC}"
cat > /opt/mt5-bot/backend/.env << EOF
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=/opt/mt5-bot/backend/trading.db
CORS_ORIGINS=https://algotradeai.net,https://www.algotradeai.net
EOF

# --- Step 7: Create Systemd Service ---
echo -e "${YELLOW}[7/10] Creating systemd service...${NC}"
cat > /etc/systemd/system/trading-bot.service << 'EOF'
[Unit]
Description=AI Trading Bot Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mt5-bot/backend
EnvironmentFile=/opt/mt5-bot/backend/.env
ExecStart=/opt/mt5-bot/backend/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable trading-bot

# --- Step 8: Configure Nginx ---
echo -e "${YELLOW}[8/10] Configuring Nginx...${NC}"
cat > /etc/nginx/sites-available/algotradeai << EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/algotradeai /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# --- Step 9: Firewall ---
echo -e "${YELLOW}[9/10] Configuring firewall...${NC}"
ufw default deny incoming
ufw default allow outgoing
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

# --- Step 10: SSL Certificate ---
echo -e "${YELLOW}[10/10] Installing SSL certificate...${NC}"
certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --email ${ADMIN_EMAIL} || true

# --- Start the Bot ---
echo -e "${YELLOW}Starting the trading bot...${NC}"
systemctl start trading-bot
sleep 3

# --- Create First Admin User ---
echo -e "${YELLOW}Creating admin user...${NC}"
cd /opt/mt5-bot/backend
source venv/bin/activate
python -c "
import requests, json
try:
    resp = requests.post('http://127.0.0.1:8000/api/auth/bootstrap', json={
        'username': '${ADMIN_USER}',
        'email': '${ADMIN_EMAIL}',
        'password': '${ADMIN_PASSWORD}'
    })
    data = resp.json()
    print(json.dumps(data, indent=2))
    if 'id' in data:
        print('Admin user created successfully!')
    else:
        print('User may already exist or error occurred.')
except Exception as e:
    print(f'Error: {e}')
"

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  SETUP COMPLETE!${NC}"
echo -e "${GREEN}==============================================${NC}"
echo ""
echo -e "${GREEN}Your bot is running at:${NC}"
echo -e "  Backend API: https://${DOMAIN}"
echo -e "  Health Check: https://${DOMAIN}/api/health"
echo ""
echo -e "${GREEN}Admin Login:${NC}"
echo -e "  Username: ${ADMIN_USER}"
echo -e "  Password: ${ADMIN_PASSWORD}"
echo -e "  Admin URL: https://www.algotradeai.net/admin"
echo ""
echo -e "${YELLOW}IMPORTANT: Change the admin password after first login!${NC}"
echo ""
echo -e "${GREEN}Useful commands:${NC}"
echo -e "  Check bot status:  systemctl status trading-bot"
echo -e "  View logs:         journalctl -u trading-bot -f"
echo -e "  Restart bot:       systemctl restart trading-bot"
echo -e "  Renew SSL:         certbot renew --dry-run"
echo ""
