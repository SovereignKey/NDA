#!/bin/bash
pkill -f "cloudflared tunnel --url" 2>/dev/null && echo "tunnel stopped"
pkill -f "server.py" 2>/dev/null && echo "server stopped"
