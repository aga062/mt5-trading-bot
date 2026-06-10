# Complete Deployment Guide: algotradeai.net

## What We're Building

```
┌─────────────────────────────────────────────────────────────┐
│                     INTERNET                                 │
│                                                              │
│  User types: https://algotradeai.net                         │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐      ┌──────────────────────────────┐    │
│  │   Vercel     │──────│   Your VPS (Linux)           │    │
│  │  (Frontend)  │ API  │   (Backend + Database)        │    │
│  │   FREE       │      │   $6/month                   │    │
│  └──────────────┘      │   - FastAPI bot                │    │
│                        │   - SQLite database            │    │
│                        │   - Runs 24/7                  │    │
│                        └──────────────────────────────┘    │
│                                   │                         │
│                                   ▼                         │
│                        ┌──────────────────────────────┐    │
│                        │   Your Home PC (Windows)     │    │
│                        │   - MetaTrader 5 Terminal    │    │
│                        │   - Must stay ON             │    │
│                        └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## BEFORE YOU START — What You Need

| Item | Where to Get | Cost | You Have It? |
|------|-------------|------|-------------|
| Domain name | Namecheap (algotradeai.net) | ~$12/year | ✅ Yes |
| VPS server | Vultr / DigitalOcean / Hetzner | ~$6/month | ⬜ No |
| GitHub account | github.com | Free | ⬜ No |
| Vercel account | vercel.com | Free | ⬜ No |
| PuTTY (Windows) | putty.org | Free | ⬜ No |

**Total monthly cost: ~$6/month** (just the VPS)

---

## PART 1: Create Your VPS (The Kitchen)

### Step 1: Sign Up for a VPS

**What is a VPS?**
Think of it as renting a computer in the cloud that NEVER turns off. Your trading bot needs to run 24/7.

**Where to get one:**
I recommend **Hetzner** (cheapest and reliable) or **Vultr** (easiest for beginners).

**What to do:**
1. Go to [hetzner.com](https://hetzner.com) or [vultr.com](https://vultr.com)
2. Sign up with your email
3. Add a payment method (credit card or PayPal)
4. Create a new server:

   **If using Hetzner:**
   - Click "Add Server"
   - Type: Shared vCPU (CX11)
   - OS: Ubuntu 22.04
   - Location: Choose closest to you (Nuremberg, Falkenstein, or Helsinki)
   - Name: `mt5-bot`
   - Click "Create & Buy"

   **If using Vultr:**
   - Click "Deploy Server" → "Cloud Compute"
   - Choose "Regular Performance"
   - Location: Choose closest city
   - OS: Ubuntu 22.04 LTS
   - Plan: $6/month (1 CPU, 1GB RAM)
   - Click "Deploy Now"

5. Wait 2-3 minutes for the server to be ready
6. **Write down the IP address** (looks like `123.45.67.89`)

> **IMPORTANT:** You'll get an email with the root password. SAVE THIS PASSWORD.

---

### Step 2: Connect to Your VPS

You need a "remote control" program to access your VPS.

**What to do:**
1. Download **PuTTY** from [putty.org](https://putty.org)
2. Open PuTTY
3. In the "Host Name" box, type your VPS IP address (e.g., `123.45.67.89`)
4. Click "Open"
5. A black window appears. It asks:
   - `login as:` → type `root` and press Enter
   - `password:` → type the password from the email (you won't see it as you type) and press Enter

**You are now inside your VPS!** Everything from here happens inside this black window.

---

### Step 3: Install Basic Software

Copy and paste each line below into the PuTTY window, then press Enter. Wait for each to finish before pasting the next.

```bash
apt update
```

This updates the software list. Wait until it finishes.

```bash
apt install -y python3 python3-pip python3-venv nginx git ufw
```

This installs:
- **Python** — the language your bot uses
- **Nginx** — a "waiter" that directs internet traffic
- **Git** — downloads code from the internet
- **UFW** — a firewall (security guard)

Wait for it to finish. This may take 2-3 minutes.

---

### Step 4: Copy Your Bot Code to the VPS

You need to move the `backend` folder from your computer to the VPS.

**What to do** (on your Windows computer, NOT in PuTTY):

1. Press Windows key, type `cmd`, and open Command Prompt
2. Type this command (replace `123.45.67.89` with YOUR actual VPS IP):

```bash
scp -r "C:\Users\adaga\OneDrive\Desktop\MT5\backend" root@123.45.67.89:/opt/mt5-bot/
```

3. It will ask for your VPS password. Type it and press Enter.
4. Wait while files copy. This may take 1-2 minutes.

**What this does:** Copies your entire backend folder to `/opt/mt5-bot/backend` on the VPS.

---

### Step 5: Set Up Python Environment

Go back to your PuTTY window and type:

```bash
cd /opt/mt5-bot/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**What this does:**
- Creates a "virtual environment" (a clean workspace)
- Installs all the libraries your bot needs (FastAPI, numpy, pandas, etc.)

Wait for this to finish. It may take 3-5 minutes.

---

### Step 6: Create Your Environment File

Your bot needs secret settings. You'll create a file with these settings.

**What to do** in PuTTY:

```bash
nano /opt/mt5-bot/backend/.env
```

A text editor opens. Type exactly this:

```
SECRET_KEY=your-super-secret-long-random-key-here-change-this-now
DATABASE_URL=/opt/mt5-bot/backend/trading.db
CORS_ORIGINS=https://algotradeai.net,https://www.algotradeai.net
```

**IMPORTANT:** Replace `your-super-secret-long-random-key-here-change-this-now` with a long random sentence. Make it at least 32 characters. For example: `MyBotKey2024-GoldTrading-XAUUSD-Secret-9876543210`

**To save and exit:**
1. Press **Ctrl+O** (the letter O)
2. Press **Enter**
3. Press **Ctrl+X**

---

### Step 7: Start Your Bot as a Service

You want the bot to start automatically when the VPS restarts.

**What to do** in PuTTY:

```bash
nano /etc/systemd/system/trading-bot.service
```

Paste this EXACT text (right-click in PuTTY to paste):

```ini
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

[Install]
WantedBy=multi-user.target
```

Save and exit (Ctrl+O, Enter, Ctrl+X).

Now enable and start the service:

```bash
systemctl daemon-reload
systemctl enable trading-bot
systemctl start trading-bot
systemctl status trading-bot
```

If you see green text saying "active (running)", it works!

**To check if it's still running later:**
```bash
systemctl status trading-bot
```

**To restart the bot after code changes:**
```bash
systemctl restart trading-bot
```

---

### Step 8: Set Up Nginx (The Waiter)

Your bot runs on port 8000, but websites use port 80 (HTTP) and 443 (HTTPS). Nginx sits at the door and forwards visitors to your bot.

**What to do** in PuTTY:

```bash
nano /etc/nginx/sites-available/algotradeai
```

Paste this (replace `api.algotradeai.net` with your domain):

```nginx
server {
    listen 80;
    server_name api.algotradeai.net;

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

Save and exit (Ctrl+O, Enter, Ctrl+X).

Now enable this config:

```bash
ln -s /etc/nginx/sites-available/algotradeai /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

If `nginx -t` says "syntax is ok", you're good.

---

### Step 9: Add HTTPS (The Green Padlock)

Browsers require HTTPS (the green lock icon). Let's Encrypt gives this for free.

**What to do** in PuTTY:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.algotradeai.net
```

It will ask:
1. **Email address** → type your email
2. **Agree to terms** → type `A` and press Enter
3. **Share email with EFF** → type `N` and press Enter
4. **Select whether to redirect HTTP to HTTPS** → type `2` (Redirect) and press Enter

Certbot automatically configures everything. Your backend now has HTTPS!

**To test renewal:**
```bash
certbot renew --dry-run
```

---

### Step 10: Open the Firewall

Your VPS blocks visitors by default. You need to open the doors.

**What to do** in PuTTY:

```bash
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw enable
```

When it asks "Command may disrupt existing ssh connections", type `y` and press Enter.

**Check status:**
```bash
ufw status
```

You should see:
```
To                         Action      From
--                         ------      ----
Nginx Full                 ALLOW       Anywhere
OpenSSH                    ALLOW       Anywhere
```

---

## PART 2: Configure Your Domain (Namecheap)

### Step 11: Point Domain to Your VPS

You need to tell Namecheap where your servers are.

**What to do:**
1. Log into [namecheap.com](https://namecheap.com)
2. Go to **Domain List** → Find `algotradeai.net` → Click **Manage**
3. Click the **Advanced DNS** tab
4. Delete any existing records (if there are any)
5. Add these records:

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A Record | `@` | `YOUR_VPS_IP` | Automatic |
| A Record | `api` | `YOUR_VPS_IP` | Automatic |
| CNAME Record | `www` | `cname.vercel-dns.com` | Automatic |

**Replace `YOUR_VPS_IP`** with the actual IP address from your VPS provider.

**Click the green checkmark to save each record.**

**What this does:**
- `algotradeai.net` → goes to your VPS (for now, we'll change this later)
- `api.algotradeai.net` → goes to your VPS (this is for the backend)
- `www.algotradeai.net` → goes to Vercel (this is for the frontend)

Wait 5-10 minutes for DNS to spread.

**Test your backend:**
Open a web browser and go to:
```
http://api.algotradeai.net/api/health
```

You should see:
```json
{"status":"ok","timestamp":"..."}
```

If you see this, your backend is live on the internet!

---

## PART 3: Deploy Frontend to Vercel

### Step 12: Create a GitHub Account

**What to do:**
1. Go to [github.com](https://github.com)
2. Sign up with your email
3. Verify your email
4. Log in

---

### Step 13: Push Your Frontend Code to GitHub

**What to do** (on your Windows computer):

1. Download Git from [git-scm.com](https://git-scm.com) and install it
2. Open Command Prompt
3. Type these commands one by one:

```bash
cd "C:\Users\adaga\OneDrive\Desktop\MT5"
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/mt5-trading-bot.git
git push -u origin main
```

**Replace `YOUR_GITHUB_USERNAME`** with your actual GitHub username.

4. When it asks for a password, use a **Personal Access Token** (not your GitHub password):
   - Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Click "Generate new token"
   - Check the `repo` box
   - Click "Generate token"
   - Copy the token and paste it as your password

**What this does:** Uploads your code to GitHub so Vercel can read it.

---

### Step 14: Connect Vercel to GitHub

**What to do:**
1. Go to [vercel.com](https://vercel.com)
2. Sign up with your GitHub account (click "Continue with GitHub")
3. Click "Add New Project"
4. Find your `mt5-trading-bot` repository and click "Import"
5. Vercel auto-detects it's a Next.js app

**Before clicking "Deploy", add environment variables:**

1. Click "Environment Variables" to expand it
2. Add this variable:

   | Name | Value |
   |------|-------|
   | `NEXT_PUBLIC_API_URL` | `https://api.algotradeai.net` |

3. Click "Deploy"

Vercel will build and deploy your frontend. Wait 2-3 minutes.

---

### Step 15: Add Your Custom Domain to Vercel

**What to do:**
1. In Vercel, go to your project
2. Click **Settings** → **Domains**
3. Type: `algotradeai.net` → Click **Add**
4. Vercel will detect that you already configured DNS in Namecheap
5. Wait a minute, then it should show a green checkmark
6. Also add: `www.algotradeai.net`

**Important:** Go back to Namecheap and change the `@` A record:
- Change `@` from your VPS IP to Vercel's IP (Vercel will show you what IP to use, or you can use a redirect)

**Better approach:** In Namecheap, set up a redirect:
1. In Namecheap Domain List → Manage → Domain
2. Under "Redirect Domain", set:
   - Source: `algotradeai.net`
   - Destination: `https://www.algotradeai.net`
3. This way `algotradeai.net` redirects to `www.algotradeai.net` which is on Vercel

---

## PART 4: Connect Everything Together

### Step 16: Update Namecheap DNS (Final Version)

Your final DNS setup should be:

| Type | Host | Value | TTL |
|------|------|-------|-----|
| URL Redirect Record | `@` | `https://www.algotradeai.net` | Unmasked |
| CNAME Record | `www` | `cname.vercel-dns.com` | Automatic |
| A Record | `api` | `YOUR_VPS_IP` | Automatic |

**What this does:**
- `algotradeai.net` → redirects to → `www.algotradeai.net` (Vercel frontend)
- `www.algotradeai.net` → Vercel (your dashboard)
- `api.algotradeai.net` → Your VPS (your backend)

---

### Step 17: Create Your First Admin User

Since regular users can't sign up anymore, you need to create the first admin.

**What to do** in PuTTY:

```bash
cd /opt/mt5-bot/backend
source venv/bin/activate
```

Now run this Python command to create your admin account:

```bash
python -c "
import requests, json
resp = requests.post('http://127.0.0.1:8000/api/auth/bootstrap', json={
    'username': 'garad',
    'email': 'agarad60@gmail.com',
    'password': 'your-strong-password-here'
})
print(json.dumps(resp.json(), indent=2))
"
```

**Replace `your-strong-password-here`** with a real password you'll remember.

You should see:
```json
{
  "id": 1,
  "username": "garad",
  "email": "agarad60@gmail.com",
  "role": "admin"
}
```

✅ Your admin account is created!

---

### Step 18: Test Everything

Open your web browser and test each URL:

| URL | What You Should See |
|-----|-------------------|
| `https://api.algotradeai.net/api/health` | `{"status":"ok",...}` |
| `https://www.algotradeai.net` | Your login page |
| `https://algotradeai.net` | Redirects to www version |

**Try logging in:**
1. Go to `https://www.algotradeai.net`
2. Log in with username `garad` and your password
3. You should see the trading dashboard

**Try admin dashboard:**
1. Go to `https://www.algotradeai.net/admin`
2. Log in with the same credentials
3. You should see the admin panel with user management

---

## PART 5: Connect MetaTrader 5 (Optional)

Your backend is on the VPS, but MT5 runs on your home PC (Windows). They need to talk to each other.

### Option A: Keep MT5 on Your Home PC (Cheaper)

Your home PC must stay on 24/7 with MT5 running.

**What to do:**
1. In your MT5 EA/settings, change the API URL from `http://127.0.0.1:8000` to:
   ```
   https://api.algotradeai.net
   ```
2. Make sure your home PC has internet 24/7
3. Make sure MT5 terminal stays open

**Problem:** If your home PC turns off, the bot can't execute trades. The VPS will still analyze the market, but can't place orders.

### Option B: Rent a Windows VPS (More Expensive, Fully Automated)

Rent a Windows VPS (~$15-20/month), install MT5 on it, and run everything in the cloud. Your home PC can be off.

**Recommended providers for Windows VPS:**
- Vultr ($20/month Windows)
- OVHcloud
- Contabo (cheapest Windows VPS)

---

## PART 6: Updating Your Bot (After Deployment)

When you change code and want to update the live bot:

### Update Backend:
```bash
# On your Windows PC, copy new files to VPS
scp -r "C:\Users\adaga\OneDrive\Desktop\MT5\backend" root@YOUR_VPS_IP:/opt/mt5-bot/

# Then in PuTTY, restart the bot
systemctl restart trading-bot
```

### Update Frontend:
```bash
# On your Windows PC, push to GitHub
cd "C:\Users\adaga\OneDrive\Desktop\MT5"
git add .
git commit -m "Update frontend"
git push

# Vercel automatically redeploys!
```

---

## TROUBLESHOOTING

### Can't connect to VPS via PuTTY
- Check that your VPS is running in the provider dashboard
- Check firewall rules in the provider dashboard
- Try waiting 5 minutes after creating the VPS

### Backend health check doesn't work
```bash
# In PuTTY, check if bot is running
systemctl status trading-bot

# Check logs
journalctl -u trading-bot -n 50

# Check if port 8000 is listening
ss -tlnp | grep 8000
```

### Frontend shows "Failed to fetch" or CORS error
- Make sure `CORS_ORIGINS` in `/opt/mt5-bot/backend/.env` includes your Vercel domain
- Restart bot: `systemctl restart trading-bot`
- Check browser console (F12) for exact error

### Domain doesn't work
- DNS takes time to spread (up to 24 hours, usually 5-10 minutes)
- Check DNS: [dnschecker.org](https://dnschecker.org)
- Make sure you replaced `YOUR_VPS_IP` with the real IP in Namecheap

### SSL/HTTPS doesn't work
```bash
# In PuTTY, test certbot
certbot renew --dry-run

# Check nginx config
nginx -t

# Restart nginx
systemctl restart nginx
```

---

## MONTHLY COSTS

| Service | Cost |
|---------|------|
| VPS (Hetzner CX11) | €4.51 (~$5) |
| Domain (Namecheap) | ~$1/month (paid yearly) |
| Vercel (Frontend) | FREE |
| Let's Encrypt SSL | FREE |
| **TOTAL** | **~$6/month** |

---

## QUICK REFERENCE: Important Commands

```bash
# Check bot status
systemctl status trading-bot

# Restart bot
systemctl restart trading-bot

# View bot logs
journalctl -u trading-bot -f

# Check nginx
systemctl status nginx
nginx -t

# Renew SSL manually
certbot renew

# Check firewall
ufw status

# Update code and restart
systemctl restart trading-bot
```

---

## YOU'RE DONE!

Your trading bot is now:
- ✅ Frontend hosted on Vercel (free, fast, always available)
- ✅ Backend running 24/7 on your VPS
- ✅ Custom domain with SSL (green padlock)
- ✅ Admin-only user registration
- ✅ MetaTrader 5 connected (if your PC stays on)

**Next step:** Start the bot from your dashboard and let it trade!
