#!/bin/bash
# HotelOS Server Setup Script
# Run once on fresh server: bash deploy/setup-server.sh

set -e

echo "🏨 HotelOS Server Setup"
echo "========================"

# 1. Install dependencies
echo "[1/6] Installing system packages..."
sudo apt update -y
sudo apt install -y nginx redis-server python3-venv certbot python3-certbot-nginx

# 2. Enable services
echo "[2/6] Enabling services..."
sudo systemctl enable redis-server nginx
sudo systemctl start redis-server nginx

# 3. Setup application directory
echo "[3/6] Setting up /opt/hotelos..."
sudo mkdir -p /opt/hotelos
sudo chown ubuntu:ubuntu /opt/hotelos

# 4. Python venv
echo "[4/6] Creating Python virtual environment..."
cd /opt/hotelos
python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

# 5. Systemd services
echo "[5/6] Installing systemd services..."

for service in reception housekeeping roomservice maintenance dashboard; do
    case $service in
        reception)    PORT=8001; EXEC="services/reception/service.py" ;;
        housekeeping) PORT=8002; EXEC="services/housekeeping/service.py" ;;
        roomservice)  PORT=8003; EXEC="services/room_service/service.py" ;;
        maintenance)  PORT=8004; EXEC="services/maintenance/service.py" ;;
        dashboard)    PORT=8080; EXEC="dashboard/server.py" ;;
    esac

    sudo tee /etc/systemd/system/hotelos-${service}.service > /dev/null << UNIT
[Unit]
Description=HotelOS ${service} Service (port ${PORT})
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/hotelos
ExecStart=/opt/hotelos/venv/bin/python ${EXEC}
Restart=always
RestartSec=3
Environment=PYTHONPATH=/opt/hotelos

[Install]
WantedBy=multi-user.target
UNIT
done

sudo systemctl daemon-reload
sudo systemctl enable hotelos-reception hotelos-housekeeping hotelos-roomservice hotelos-maintenance hotelos-dashboard

# 6. Nginx config
echo "[6/6] Configuring Nginx..."
sudo cp deploy/nginx.conf /etc/nginx/sites-available/hotelos
sudo ln -sf /etc/nginx/sites-available/hotelos /etc/nginx/sites-enabled/hotelos
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "✅ Setup complete!"
echo "   Start services: sudo systemctl start hotelos-reception hotelos-housekeeping hotelos-roomservice hotelos-maintenance hotelos-dashboard"
echo "   SSL: sudo certbot --nginx -d programming.asilbek.tech"
