#!/bin/bash
# Cloudflare Tunnel Setup for Idea Factory API
# Run this script on the EC2 instance to set up secure tunnel access
set -e

TUNNEL_NAME="idea-factory-api"
HOSTNAME="api.irhuman.ai"

echo "=== Cloudflare Tunnel Setup for Idea Factory ==="
echo ""

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    sudo dpkg -i cloudflared.deb
    rm cloudflared.deb
    echo "cloudflared installed successfully"
else
    echo "cloudflared already installed: $(cloudflared --version)"
fi

# Login to Cloudflare (interactive - opens browser)
echo ""
echo "=== Step 1: Login to Cloudflare ==="
echo "This will open a browser window. Select your Cloudflare account."
read -p "Press Enter to continue..."
cloudflared tunnel login

# Create the tunnel
echo ""
echo "=== Step 2: Create Tunnel ==="
if cloudflared tunnel list | grep -q "$TUNNEL_NAME"; then
    echo "Tunnel '$TUNNEL_NAME' already exists"
    TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
else
    cloudflared tunnel create "$TUNNEL_NAME"
    TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
    echo "Created tunnel with ID: $TUNNEL_ID"
fi

# Create config directory
mkdir -p ~/.cloudflared

# Create config file
echo ""
echo "=== Step 3: Configure Tunnel ==="
cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /home/ubuntu/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $HOSTNAME
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false
  - service: http_status:404
EOF
echo "Created config at ~/.cloudflared/config.yml"

# Setup DNS routing
echo ""
echo "=== Step 4: Configure DNS ==="
echo "Setting up DNS CNAME for $HOSTNAME..."
cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" || echo "DNS may already be configured"

# Install systemd service
echo ""
echo "=== Step 5: Install Systemd Service ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$SCRIPT_DIR/cloudflared.service" /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
echo "Systemd service installed and enabled"

# Start the tunnel
echo ""
echo "=== Step 6: Start Tunnel ==="
sudo systemctl start cloudflared
sleep 3
if systemctl is-active --quiet cloudflared; then
    echo "Tunnel started successfully!"
else
    echo "Warning: Tunnel may not have started. Check: sudo journalctl -u cloudflared -f"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Your API will be available at: https://$HOSTNAME"
echo ""
echo "Useful commands:"
echo "  Check status:  sudo systemctl status cloudflared"
echo "  View logs:     sudo journalctl -u cloudflared -f"
echo "  Restart:       sudo systemctl restart cloudflared"
echo "  Test tunnel:   cloudflared tunnel info $TUNNEL_NAME"
