#!/usr/bin/env bash
# Run the CineWhy demo locally on macOS or Linux (Windows: start.bat). The server loads the newest
# artifacts/vN that has a manifest, else artifacts/.
#
#   bash start.sh
#
set -u
cd "$(dirname "$0")"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

if [ -x venv/bin/python ]; then
  PY=venv/bin/python
elif [ -x venv/Scripts/python.exe ]; then
  PY=venv/Scripts/python.exe # a Windows venv used from Git Bash
else
  echo "The virtual environment is missing. Run: bash setup.sh"
  exit 1
fi

found=""
for dir in artifacts/v*/; do
  [ -f "${dir}manifest.json" ] && found=1
done
[ -f artifacts/manifest.json ] && found=1
if [ -z "$found" ]; then
  echo "No data found. Unzip the ready-made data zip into artifacts/v13 so that"
  echo "artifacts/v13/manifest.json exists. Steps: README.md, \"Get the data\"."
  exit 1
fi

# Open a page in the default browser: "open" on macOS, "xdg-open" on Linux, "start" in Git Bash.
open_url() {
  if command -v open >/dev/null 2>&1; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1"
  elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$1"
  else echo "Open $1 in your browser."; fi
}

# A copy already listening on port 8000 would make the new one fail to start, and the browser would
# show whatever that old copy serves. Say so instead of opening a confusing page.
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "CineWhy, or another program, is already running on port 8000."
  echo "Close that terminal (or press Ctrl+C in it) and run this again, so the newest build is served."
  echo "Opening the copy that is running now..."
  open_url "http://localhost:8000/"
  exit 0
fi

echo "Starting CineWhy. The first load checks about 1.8 GB of data files and takes up to a minute;"
echo "the browser opens by itself as soon as the site is ready. Press Ctrl+C here to stop it."
cat <<'EOF'

------------------------------------------------------------------
 WANT A FRIEND TO JOIN YOU? Make a temporary public link:
------------------------------------------------------------------
 Once, ever: install the free tool.
     macOS:   brew install cloudflared
     Linux:   see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

 Every time you want a new link:
   1. Leave THIS terminal open. It is the server.
   2. Open a SECOND terminal and run
          cloudflared tunnel --url http://localhost:8000
   3. After a few seconds it prints an address that ends in
      trycloudflare.com . Open THAT address in your browser (not
      localhost), then Profile, Watch together, Start a room, and
      send your friend the invite link.
   4. Ctrl+C in the second terminal closes the link. A new link is
      made each time, so send the new one.
 While the link is up, anyone who has it can open the app.
 Full guide: README.md, "Share it with a friend".
------------------------------------------------------------------

EOF

# Open the browser only once the server answers: it needs about 30 seconds to start, and a browser
# opened sooner shows a "can't connect" page that looks like a broken site.
(
  for _ in $(seq 1 240); do
    if curl -fs -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      open_url "http://localhost:8000/"
      break
    fi
    sleep 1
  done
) &

exec "$PY" -m uvicorn api.main:app --port 8000
