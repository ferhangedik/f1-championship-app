# Deployment Guide — Ubuntu VPS (nginx + gunicorn + PostgreSQL) -- AI Genarated

This guide takes the application from the local Windows development setup to a public,
HTTPS-secured website on your own Linux VPS (e.g. DigitalOcean, Hetzner, Contabo). You can
follow it now and simply attach the domain at the end once you have bought it.

Stack on the server: **Ubuntu 22.04/24.04 · PostgreSQL · Python venv · Gunicorn · Nginx · Certbot (HTTPS)**.

---

## 0. Before you start
- A VPS with a public IP and SSH access (`ssh root@SERVER_IP`).
- (Later) a domain name; you will point its DNS **A record** to `SERVER_IP`.
- Replace placeholders: `SERVER_IP`, `yourdomain.com`, and the database password `STRONGPASS`.

---

## 1. Create a non-root user and basic firewall
```bash
adduser f1
usermod -aG sudo f1
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
su - f1
```

## 2. Install system packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip postgresql nginx git
```

## 3. Create the database and a password-protected user
On the server PostgreSQL uses **password authentication** (not the `trust` used locally).
```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE hfg_f1db;
CREATE USER f1user WITH PASSWORD 'STRONGPASS';
GRANT ALL PRIVILEGES ON DATABASE hfg_f1db TO f1user;
\c hfg_f1db
GRANT ALL ON SCHEMA public TO f1user;
SQL
```

## 4. Get the code and create a virtual environment
```bash
cd ~
git clone <YOUR_REPO_URL> f1-app    # or upload the f1-app folder with scp/rsync
cd f1-app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-prod.txt   # gunicorn
```

## 5. Configure environment variables
Create `.env` in the project folder:
```bash
cat > .env <<'ENV'
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=hfg_f1db
DB_USER=f1user
DB_PASSWORD=STRONGPASS
SECRET_KEY=PASTE_A_LONG_RANDOM_STRING_HERE
FLASK_DEBUG=0
ENV
```
Generate a secret key: `python3 -c "import secrets; print(secrets.token_hex(32))"`.

## 6. Create the schema and load data
Create the tables:
```bash
PGPASSWORD=STRONGPASS psql -h 127.0.0.1 -U f1user -d hfg_f1db -f schema.sql
PGPASSWORD=STRONGPASS psql -h 127.0.0.1 -U f1user -d hfg_f1db -f procedures.sql
```
Then either **(a)** load fresh on the server:
```bash
python ergast_loader.py --season 2025
python ergast_loader.py --season 2026
python data_loader.py --season 2026 --round 20 --photos-only   # driver photos (FastF1)
```
…or **(b, recommended)** copy your already-populated local database so you keep the exact
data. On Windows (local):
```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h 127.0.0.1 -U postgres -d hfg_f1db -Fc -f hfg_f1db.dump
scp hfg_f1db.dump f1@SERVER_IP:/home/f1/f1-app/
```
On the server:
```bash
PGPASSWORD=STRONGPASS pg_restore -h 127.0.0.1 -U f1user -d hfg_f1db --no-owner --clean --if-exists hfg_f1db.dump
```

Create the admin account:
```bash
python create_admin.py admin "A_STRONG_ADMIN_PASSWORD"
```

## 7. Test with Gunicorn
```bash
gunicorn --bind 127.0.0.1:8080 wsgi:app
# visit http://SERVER_IP:8080 only if you temporarily open the port; otherwise continue.
# Ctrl+C to stop.
```

## 8. Run Gunicorn as a systemd service
```bash
sudo tee /etc/systemd/system/f1app.service > /dev/null <<'UNIT'
[Unit]
Description=F1 Analytics (Gunicorn)
After=network.target postgresql.service

[Service]
User=f1
Group=www-data
WorkingDirectory=/home/f1/f1-app
Environment="PATH=/home/f1/f1-app/.venv/bin"
ExecStart=/home/f1/f1-app/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8080 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now f1app
sudo systemctl status f1app   # should be "active (running)"
```

## 9. Nginx reverse proxy
```bash
sudo tee /etc/nginx/sites-available/f1app > /dev/null <<'NGINX'
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;   # or SERVER_IP for now

    location /static/ {
        alias /home/f1/f1-app/static/;
        expires 7d;
    }
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

sudo ln -s /etc/nginx/sites-available/f1app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
The site is now reachable at `http://SERVER_IP` (or your domain once DNS points to it).

## 10. Point the domain
At your domain registrar, create DNS records:
```
A    @     SERVER_IP
A    www   SERVER_IP
```
Wait for propagation (minutes to a few hours), then `http://yourdomain.com` should load.

## 11. Enable HTTPS (free, automatic)
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```
Certbot installs the certificate, switches Nginx to HTTPS and sets up auto-renewal.

## 12. Updating later
```bash
cd ~/f1-app && git pull
source .venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart f1app
```

---

### Notes
- Keep `FLASK_DEBUG=0` in production; never expose the Flask development server directly.
- The application binds Gunicorn to `127.0.0.1` only; all public traffic goes through Nginx.
- Database, Gunicorn and Nginx all start automatically on reboot via systemd.