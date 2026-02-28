#!/bin/bash
# TweetAgent EC2 Deploy Script
# Run this on a fresh Ubuntu 22.04+ EC2 instance
# Usage: bash deploy.sh

set -e

echo "========================================="
echo "  TweetAgent — EC2 Deployment"
echo "========================================="

# Update system
echo ">>> Updating system..."
sudo apt-get update -y
sudo apt-get upgrade -y

# Install Docker
echo ">>> Installing Docker..."
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# Clone or update repo
if [ -d "/home/ubuntu/Social-agents" ]; then
    echo ">>> Updating existing repo..."
    cd /home/ubuntu/Social-agents
    git pull
else
    echo ">>> Cloning repo..."
    cd /home/ubuntu
    git clone https://github.com/YOUR_USERNAME/Social-agents.git
    cd Social-agents
fi

# Check for .env
if [ ! -f ".env" ]; then
    echo ""
    echo "========================================="
    echo "  SETUP REQUIRED: Create .env file"
    echo "========================================="
    echo ""
    echo "Copy the example and fill in your keys:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    echo "Then run: docker compose up -d --build"
    echo ""
    exit 0
fi

# Build and run
echo ">>> Building and starting TweetAgent..."
sudo docker compose up -d --build

echo ""
echo "========================================="
echo "  TweetAgent is LIVE!"
echo "========================================="
echo ""
echo "  Dashboard: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8000"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f          # View logs"
echo "    docker compose restart           # Restart"
echo "    docker compose down              # Stop"
echo "    docker compose up -d --build     # Rebuild & start"
echo ""
