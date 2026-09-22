#!/bin/bash
# Destructive integration test: run ONLY in a disposable Debian 13 container.
# Uses the built packages, never imports the checkout's application modules.
set -euo pipefail
artifacts=$(realpath "${1:?Usage: test-debian-release.sh ARTIFACTS LOG_DIRECTORY}")
logs=$(realpath -m "${2:?Log directory required}")
repo=$(cd "$(dirname "$0")/.." && pwd)
if [ ! -f /.dockerenv ] && [ ! -f /run/.containerenv ]; then
    echo 'This test must run in a disposable container.' >&2
    exit 1
fi
if [ -e /etc/nipap/nipap.conf ]; then
    echo 'Refusing to overwrite an existing NIPAP installation.' >&2
    exit 1
fi
mkdir -p "$logs"
exec > >(tee "$logs/install-and-test.log") 2>&1
export DEBIAN_FRONTEND=noninteractive
daemon_pid=
cleanup() {
    result=$?
    if [ -n "$daemon_pid" ]; then
        kill "$daemon_pid" 2>/dev/null || true
        wait "$daemon_pid" 2>/dev/null || true
    fi
    exit "$result"
}
trap cleanup EXIT

# NIPAP's supplemental repository provides flask-restx and flask-xml-rpc-re.
curl -fsSLo /usr/share/keyrings/nipap.asc https://spritelink.github.io/NIPAP/nipap.gpg.key
echo 'deb [signed-by=/usr/share/keyrings/nipap.asc] https://spritelink.github.io/NIPAP/repos/apt testing main extra' > /etc/apt/sources.list.d/nipap.list
apt-get update
apt-get install -y --no-install-recommends postgresql-17 postgresql-17-ip4r ssl-cert
pg_ctlcluster 17 main start

debconf-set-selections <<'EOF'
nipapd nipapd/database_host string localhost
nipapd nipapd/local_db_autoconf boolean true
nipapd nipapd/local_db_upgrade boolean false
nipapd nipapd/startup boolean false
nipap-www nipap-www/autouser boolean true
nipap-www nipap-www/auto_secret_key boolean true
EOF
mapfile -d '' packages < <(find "$artifacts" -name '*.deb' ! -name 'nipap-whoisd_*' -print0)
if [ "${#packages[@]}" -ne 5 ]; then
    echo "Expected five NIPAP packages, found ${#packages[@]}" >&2
    exit 1
fi
apt-get install -y "${packages[@]}"
dpkg-query -W -f='${Package}\t${Version}\n' nipapd nipap-common python3-pynipap nipap-www nipap-cli > "$logs/installed-versions.txt"
dpkg-query -W -f='${Package}\t${Version}\n' > "$logs/dependencies.txt"

# Use TCP/password authentication for tests which directly access the backend.
sed -i -e 's/^db_host *=.*/db_host = 127.0.0.1/' \
    -e 's/^syslog *=.*/syslog = false/' -e 's/^forks *=.*/forks = 1/' \
    /etc/nipap/nipap.conf
nipap-passwd add -u unittest -p gottatest -n 'Release tests'
nipap-passwd add -u readonly -p gottatest --readonly -n 'Read-only release tests'
# Install order can leave web debconf setup pending until the backend exists.
dpkg-reconfigure -f noninteractive nipap-www
sed -e 's/username = guest/username = unittest/' -e 's/password = guest/password = gottatest/' \
    /etc/.nipaprc > "$HOME/.nipaprc"
chmod 0600 "$HOME/.nipaprc"

runuser -u nipap -- /usr/bin/nipapd --foreground --no-pid-file --auto-install-db > "$logs/nipapd.log" 2>&1 &
daemon_pid=$!
python3 - <<'PY'
import socket
import time
import xmlrpc.client
socket.setdefaulttimeout(2)
deadline = time.monotonic() + 60
while True:
    try:
        with xmlrpc.client.ServerProxy('http://unittest:gottatest@127.0.0.1:1337/XMLRPC') as server:
            server.list_vrf({'auth': {'authoritative_source': 'release-test'}, 'vrf': {}})
        break
    except (OSError, xmlrpc.client.Error):
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
PY

# Copy only tests: their relative source import paths must not find the checkout.
work=$(mktemp -d)
cp -r "$repo/tests" "$work/tests"
mkdir "$work/nipap-cli"
ln -s /usr/bin/nipap "$work/nipap-cli/nipap"
cd "$work"
unset PYTHONPATH
for suite in test_nipapd_startup test_web_audit test_xmlrpc nipaptest test_cli test_nipap_ro test_rest; do
    python3 -m unittest discover -s tests -p "$suite.py"
done
python3 - <<'PY'
from pathlib import Path
import nipap
import nipapwww
import pynipap
from nipap import db_schema
for module in (nipap, nipapwww, pynipap):
    assert '/usr/lib/python3/dist-packages/' in module.__file__, module.__file__
assert len(db_schema.upgrade) == nipap.__db_version__ - 1
app = nipapwww.create_app()
app.config['TESTING'] = True
with app.test_client() as client:
    assert client.get('/auth/login').status_code == 200
    response = client.post('/auth/login', data={'username': 'unittest', 'password': 'gottatest'}, follow_redirects=True)
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session['user'] == 'unittest'
static = Path(nipapwww.__file__).parent / 'static'
assert any(static.rglob('*.js')) and any(static.rglob('*.css'))
print('Installed web application login, static assets and schema checks passed.')
PY
/usr/bin/nipap vrf list
