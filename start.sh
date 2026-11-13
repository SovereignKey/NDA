#!/bin/bash
# Starts the NDA signing server and a Cloudflare quick tunnel, then prints the public link.
# Stop both with:  ./stop.sh
cd "$(dirname "$0")"
mkdir -p logs
if ! lsof -nP -iTCP:${PORT:-8790} -sTCP:LISTEN >/dev/null; then
  nohup python3 server.py > logs/server.log 2>&1 &
  sleep 1
fi
pkill -f "cloudflared tunnel --url" 2>/dev/null
nohup cloudflared tunnel --url http://localhost:${PORT:-8790} > logs/tunnel.log 2>&1 &
echo "Waiting for the tunnel..."
for i in $(seq 1 20); do
  sleep 2
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' logs/tunnel.log | head -1)
  [ -n "$URL" ] && break
done
[ -z "$URL" ] && { echo "Tunnel did not start; see logs/tunnel.log"; exit 1; }
TOKEN=$(cat .admin-token 2>/dev/null)
echo
echo "Signing link for Stephen:"
echo "  $URL/?name=Stephen%20Hoefer&email=SHoefer%40mtvrn.com"
echo
echo "Your admin / countersign page (keep private):"
echo "  http://localhost:${PORT:-8790}/admin?token=$TOKEN"
echo
echo "The public link can take a minute or two to start resolving. Keep this Mac awake and both"
echo "processes running until the NDA is signed; the link changes if the tunnel restarts."
