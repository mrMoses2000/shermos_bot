# Shermos Bot — Deployment Guide

## Prerequisites

- AWS Security Group: **port 88 open** (TCP, 0.0.0.0/0)
- Server: `ssh aws-shermos1-frankfurt` (Ubuntu 24.04, user `ubuntu`)
- Gemini CLI: authorized via OAuth (`gemini` → complete OAuth → Ctrl+C)
- GitHub SSH key configured on server

## Deploy (3 commands)

### 1. Clone project on server

```bash
ssh aws-shermos1-frankfurt
git clone git@github.com:mrMoses2000/shermos_bot.git ~/shermos-bot
```

### 2. Copy `.env` from Mac

`.env` contains real tokens and is gitignored — it won't appear after clone.
Run this **from your Mac**:

```bash
scp /Users/mosesvasilenko/shermos-bot/.env ubuntu@3.79.24.73:~/shermos-bot/.env
```

### 3. Run deployment script

```bash
ssh aws-shermos1-frankfurt
cd ~/shermos-bot
chmod +x run.sh
./run.sh
```

`run.sh` does everything automatically:
1. Validates `.env` (checks tokens aren't `replace_me`)
2. Installs Docker, Python deps, OpenGL libs
3. Generates self-signed SSL certificate
4. Starts PostgreSQL + Redis (Docker Compose)
5. Creates Python venv + installs requirements
6. Runs database migrations
7. Seeds default prices & materials
8. Registers Telegram webhooks (both bots)
9. Creates + starts systemd services
10. Health check

Script is **idempotent** — safe to re-run after `git pull`.

## Update deployment

```bash
cd ~/shermos-bot
git pull origin main
./run.sh
```

## Useful commands

```bash
# Logs
sudo journalctl -u shermos-webhook -f
sudo journalctl -u shermos-worker -f
docker compose logs -f

# Restart
sudo systemctl restart shermos-webhook shermos-worker

# Status
sudo systemctl status shermos-webhook shermos-worker
curl -k https://localhost:88/health
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `.env not found` | `scp` from Mac (see step 2) |
| Webhook health check fails | Wait 5s, retry. Check: `sudo journalctl -u shermos-webhook -n 30` |
| Telegram webhook error | Port 88 not open in AWS Security Group |
| Gemini CLI not found | `npm install -g @google/gemini-cli` then `gemini` for OAuth |
| PostgreSQL connection refused | `docker compose ps` — check if postgres is running |
| Permission denied (Docker) | Re-login after `sudo usermod -aG docker ubuntu` |
