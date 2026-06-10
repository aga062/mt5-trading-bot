---
description: Deploy frontend to Vercel and backend to VPS
tags: [deployment, vercel, vps]
---

# Deploy: Vercel Frontend + VPS Backend

## Prerequisites

- A Linux VPS (DigitalOcean, Vultr, Hetzner, etc.)
- A Vercel account (free)
- GitHub account (to connect Vercel)
- Domain name (optional, but recommended)

---

## Step 1: Deploy Backend to VPS

### 1.1 SSH into your VPS

```bash
ssh root@YOUR_VPS_IP
```

### 1.2 Install dependencies

```bash
# Ubuntu/Debian
apt update && apt install -y python3 python3-pip python3-venv git nginx

# Install MetaTrader5 if running MT5 on VPS (Windows VPS recommended for MT5)
```

### 1.3 Clone/upload your project

```bash
cd /opt
git clone YOUR_REPO_URL mt5-trading-bot
cd mt5-trading-bot/backend
```

Or use `scp` to copy files from your local machine:

```bash
# From your local machine
scp -r backend/ root@YOUR_VPS_IP:/opt/mt5-trading-bot/
```

### 1.4 Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 1.5 Create environment file

```bash
nano /opt/mt5-trading-bot/backend/.env
```

Add:

```
SECRET_KEY=your-very-secure-random-key-here
DATABASE_URL=/opt/mt5-trading-bot/backend/trading.db
```

### 1.6 Test the backend

```bash
cd /opt/mt5-trading-bot/backend
source venv/bin/activate
python -c "import main; print('OK')"
```

### 1.7 Create systemd service

```bash
nano /etc/systemd/system/trading-bot.service
```

Paste:

```ini
[Unit]
Description=AI Trading Bot Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mt5-trading-bot/backend
Environment=PYTHONPATH=/opt/mt5-trading-bot/backend
Environment=SECRET_KEY=your-very-secure-random-key-here
ExecStart=/opt/mt5-trading-bot/backend/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable trading-bot
systemctl start trading-bot
systemctl status trading-bot
```

### 1.8 Set up Nginx reverse proxy (with SSL)

```bash
nano /etc/nginx/sites-available/trading-bot
```

Paste:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

Enable:

```bash
ln -s /etc/nginx/sites-available/trading-bot /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

### 1.9 Add SSL with Certbot

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.yourdomain.com
```

Your backend is now live at `https://api.yourdomain.com`

---

## Step 2: Deploy Frontend to Vercel

### 2.1 Push code to GitHub

Make sure your frontend code is in a GitHub repository.

### 2.2 Import project in Vercel

1. Go to [vercel.com](https://vercel.com) → Sign in with GitHub
2. Click **Add New Project**
3. Import your GitHub repo
4. Vercel should auto-detect Next.js

### 2.3 Configure environment variables

In Vercel project settings, add:

| Name | Value | Example |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Your VPS backend URL | `https://api.yourdomain.com` |

### 2.4 Update CORS on backend

In `backend/main.py`, update the CORS origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.vercel.app"],  # Your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Or use `"*"` for testing (not recommended for production).

### 2.5 Deploy

Click **Deploy** in Vercel. Your frontend will be live at something like:
`https://mt5-trading-bot.vercel.app`

---

## Step 3: Verify

1. Visit your Vercel frontend URL
2. Try logging in — it should hit your VPS backend
3. Check VPS logs: `journalctl -u trading-bot -f`

---

## Troubleshooting

### CORS errors
- Make sure `allow_origins` in `main.py` includes your Vercel domain
- If using `"*"`, `allow_credentials=True` may cause issues — use explicit origins

### Backend not reachable
- Check firewall: `ufw allow 80 && ufw allow 443`
- Check Nginx: `systemctl status nginx`
- Check service: `systemctl status trading-bot`

### Database issues
- Make sure `DATABASE_URL` path exists on VPS
- Run `init_db()` at least once by starting the app

---

## Optional: Custom Domain

1. In Vercel project settings → Domains → Add your domain
2. In your Namecheap DNS, add a CNAME:
   - Host: `www` or `@`
   - Value: `cname.vercel-dns.com`
3. Vercel will handle SSL automatically
