# Shermos Bot — Deployment Guide

## Prerequisites

- Server: AWS EC2 Frankfurt (3.79.24.73), Ubuntu 24.04, user `ubuntu`
- SSH: `ssh aws-shermos1-frankfurt`
- Python 3.12+ on server
- GitHub repo: `git@github.com:mrMoses2000/shermos_bot.git`

---

## Step 1: Open Port 88 in AWS Security Group

AWS Console → EC2 → Security Groups → Inbound Rules → Add Rule:
- Type: Custom TCP
- Port: 88
- Source: 0.0.0.0/0 (Telegram needs to reach it)

---

## Step 2: Install Docker + Docker Compose on server

```bash
ssh aws-shermos1-frankfurt

sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
# Re-login to apply group
exit
ssh aws-shermos1-frankfurt
```

---

## Step 3: Install Gemini CLI on server

```bash
# Install Node.js 22 (Gemini CLI requires it)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# Install Gemini CLI globally
sudo npm install -g @anthropic-ai/gemini-cli@latest
# OR if using Google's package:
sudo npm install -g @anthropic-ai/claude-code@latest

# Verify
gemini --version
```

> **Note**: Check the actual package name. If Gemini CLI is installed via
> a different method on your server, verify with `which gemini` and
> `gemini --version`.

---

## Step 4: Clone project and configure

```bash
cd ~
git clone git@github.com:mrMoses2000/shermos_bot.git shermos-bot
cd shermos-bot

# Create .env from template
cp .env.example .env
```

Edit `.env` — fill in these values:

```bash
nano .env
```

| Variable | How to get |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Already generated (copy from Mac .env) |
| `MANAGER_BOT_TOKEN` | Second bot from @BotFather |
| `MANAGER_WEBHOOK_SECRET` | Already generated (copy from Mac .env) |
| `MANAGER_CHAT_IDS` | Your Telegram user ID (from @userinfobot) |
| `POSTGRES_PASSWORD` | Already generated (copy from Mac .env) |
| `GEMINI_API_KEY` | From https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-3-flash-preview` (already set) |

---

## Step 5: Generate self-signed SSL certificate

```bash
cd ~/shermos-bot
mkdir -p certs
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout certs/webhook.key \
  -x509 -days 3650 \
  -out certs/webhook.pem \
  -subj "/CN=3.79.24.73"
```

---

## Step 6: Start PostgreSQL + Redis

```bash
cd ~/shermos-bot

# Update docker-compose.yml POSTGRES_PASSWORD to match .env
# Then start services:
docker compose up -d

# Verify
docker compose ps
docker compose logs postgres
docker compose logs redis
```

---

## Step 7: Set up Python environment

```bash
cd ~/shermos-bot

# System deps for pyrender (headless OpenGL)
sudo apt install -y python3-venv python3-dev build-essential \
  libegl1-mesa-dev libgles2-mesa-dev libgl1-mesa-dev \
  libosmesa6-dev freeglut3-dev

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install deps
pip install --upgrade pip
pip install -r requirements.txt

# Set headless rendering
export PYOPENGL_PLATFORM=egl
```

---

## Step 8: Run database migrations

```bash
cd ~/shermos-bot
source .venv/bin/activate

# Connect to PostgreSQL and create user/db
docker compose exec postgres psql -U postgres -c \
  "CREATE USER shermos WITH PASSWORD '$(grep POSTGRES_PASSWORD .env | cut -d= -f2)';"
docker compose exec postgres psql -U postgres -c \
  "CREATE DATABASE shermos_bot OWNER shermos;"

# Run migrations
for f in migrations/*.sql; do
  echo "Running $f..."
  docker compose exec -T postgres psql -U shermos -d shermos_bot < "$f"
done
```

---

## Step 9: Register Telegram webhooks

```bash
source .venv/bin/activate

# Client bot webhook
CLIENT_TOKEN=$(grep TELEGRAM_BOT_TOKEN .env | cut -d= -f2)
CLIENT_SECRET=$(grep TELEGRAM_WEBHOOK_SECRET .env | cut -d= -f2)

curl -F "url=https://3.79.24.73:88/webhook/client" \
     -F "certificate=@certs/webhook.pem" \
     -F "secret_token=$CLIENT_SECRET" \
     -F "allowed_updates=[\"message\",\"callback_query\",\"edited_message\"]" \
     "https://api.telegram.org/bot${CLIENT_TOKEN}/setWebhook"

# Manager bot webhook
MANAGER_TOKEN=$(grep MANAGER_BOT_TOKEN .env | cut -d= -f2)
MANAGER_SECRET=$(grep MANAGER_WEBHOOK_SECRET .env | cut -d= -f2)

curl -F "url=https://3.79.24.73:88/webhook/manager" \
     -F "certificate=@certs/webhook.pem" \
     -F "secret_token=$MANAGER_SECRET" \
     -F "allowed_updates=[\"message\",\"callback_query\"]" \
     "https://api.telegram.org/bot${MANAGER_TOKEN}/setWebhook"

# Verify
curl "https://api.telegram.org/bot${CLIENT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

---

## Step 10: Create systemd services

### Webhook service

```bash
sudo tee /etc/systemd/system/shermos-webhook.service << 'EOF'
[Unit]
Description=Shermos Webhook Server
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shermos-bot
Environment=PYOPENGL_PLATFORM=egl
ExecStart=/home/ubuntu/shermos-bot/.venv/bin/python run_webhook.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### Worker service

```bash
sudo tee /etc/systemd/system/shermos-worker.service << 'EOF'
[Unit]
Description=Shermos Queue Worker
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shermos-bot
Environment=PYOPENGL_PLATFORM=egl
ExecStart=/home/ubuntu/shermos-bot/.venv/bin/python run_worker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### Start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable shermos-webhook shermos-worker
sudo systemctl start shermos-webhook shermos-worker

# Check status
sudo systemctl status shermos-webhook
sudo systemctl status shermos-worker

# View logs
sudo journalctl -u shermos-webhook -f
sudo journalctl -u shermos-worker -f
```

---

## Step 11: Verify everything works

```bash
# 1. Check webhook is listening
curl -k https://localhost:88/health

# 2. Check PostgreSQL
docker compose exec postgres psql -U shermos -d shermos_bot -c "\dt"

# 3. Check Redis
docker compose exec redis redis-cli ping

# 4. Check Gemini CLI
source .venv/bin/activate
echo "Скажи привет" | gemini

# 5. Send test message to bot in Telegram
# Open your bot in Telegram and send: /start
```

---

## Updating the deployment

```bash
cd ~/shermos-bot
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart shermos-webhook shermos-worker
```
