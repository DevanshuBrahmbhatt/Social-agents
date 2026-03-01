#!/bin/bash
# TweetAgent — Production Deploy Script
# Run on a fresh Ubuntu 22.04+ EC2 instance
# Usage: bash deploy.sh

set -e

echo "========================================="
echo "  TweetAgent — Production Deployment"
echo "  Domain: twitter.dagent.shop"
echo "========================================="

# Update system
echo ">>> Updating system..."
sudo apt-get update -y && sudo apt-get upgrade -y

# Install Docker
echo ">>> Installing Docker..."
if ! command -v docker &> /dev/null; then
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker $USER
    echo ">>> Docker installed"
else
    echo ">>> Docker already installed"
fi

# Clone or update repo
REPO_DIR="/home/ubuntu/Social-agents"
if [ -d "$REPO_DIR" ]; then
    echo ">>> Updating existing repo..."
    cd "$REPO_DIR"
    git pull
else
    echo ">>> Cloning repo..."
    cd /home/ubuntu
    git clone https://github.com/DevanshuBrahmbhatt/Social-agents.git
    cd Social-agents
fi

# Check for .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "========================================="
    echo "  SETUP REQUIRED: Edit .env file"
    echo "========================================="
    echo ""
    echo "  nano .env"
    echo ""
    echo "  Fill in your API keys, then run:"
    echo "  sudo docker compose up -d --build"
    echo ""
    exit 0
fi

# Update Twitter OAuth callback to production URL
echo ">>> Updating OAuth callback URL..."
if grep -q "localhost" .env; then
    sed -i 's|TWITTER_REDIRECT_URI=.*|TWITTER_REDIRECT_URI=https://twitter.dagent.shop/auth/callback|g' .env
    echo "  Updated TWITTER_REDIRECT_URI to https://twitter.dagent.shop/auth/callback"
fi

# Build and run
echo ">>> Building and starting TweetAgent..."
sudo docker compose up -d --build

echo ""
echo "========================================="
echo "  TweetAgent is LIVE!"
echo "========================================="
echo ""
echo "  URL: https://twitter.dagent.shop"
echo ""
echo "  Commands:"
echo "    sudo docker compose logs -f          # View logs"
echo "    sudo docker compose restart          # Restart"
echo "    sudo docker compose down             # Stop"
echo "    sudo docker compose up -d --build    # Rebuild"
echo ""
