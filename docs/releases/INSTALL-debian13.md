# Axians NIPAP on Debian 13

These instructions prepare a **new Debian 13 server for migration** from an
existing NIPAP installation. Run administrator commands as root. The release
targets Debian 13; its integration tests run on amd64.

## Download and verify

Download the five core `.deb` files, `SHA256SUMS`, and the remaining assets from
the same Axians GitHub Release into an empty directory. If all assets are present:

```sh
sha256sum -c SHA256SUMS
```

If you downloaded only the packages and checksum file:

```sh
sha256sum --ignore-missing -c SHA256SUMS
```

Checksums detect corruption; obtain both the packages and checksums from the
intended release over HTTPS.

## Install prerequisites

```sh
apt update
apt install ca-certificates curl postgresql-17 postgresql-17-ip4r
curl -fsSLo /tmp/nipap.asc https://spritelink.github.io/NIPAP/nipap.gpg.key
install -m 0644 /tmp/nipap.asc /usr/share/keyrings/nipap.asc
echo 'deb [signed-by=/usr/share/keyrings/nipap.asc] https://spritelink.github.io/NIPAP/repos/apt testing main extra' > /etc/apt/sources.list.d/nipap.list
apt update
```

The supplemental repository supplies `python3-flask-restx` and
`python3-flask-xml-rpc-re`. APT must successfully authenticate its metadata before
installation. The release does not bundle those dependencies.

## Install without initializing the migration destination

Keep the service stopped until the old database and authentication are restored:

```sh
systemctl mask nipapd.service
debconf-set-selections <<'EOF'
nipapd nipapd/database_host string localhost
nipapd nipapd/local_db_autoconf boolean false
nipapd nipapd/local_db_upgrade boolean false
nipapd nipapd/startup boolean false
nipapd nipapd/sqlite_upgrade boolean false
nipap-www nipap-www/autouser boolean false
nipap-www nipap-www/auto_secret_key boolean true
EOF
DEBIAN_FRONTEND=noninteractive apt install \
  ./nipap-common_*.deb ./nipapd_*.deb ./python3-pynipap_*.deb \
  ./nipap-www_*.deb ./nipap-cli_*.deb
```

Install only one release's files from this directory. The optional whois daemon
is not included in this command.

## Migration preparation

1. Back up the source PostgreSQL database and required role definitions. Use a
   consistent backup of `/etc/nipap/local_auth.db` if SQLite authentication is
   enabled, and save `/etc/nipap`, web server configuration and TLS configuration.
2. Use PostgreSQL 17's `pg_dump` against PostgreSQL 9.6 and restore into an empty
   destination database. Install the required extensions and restore required
   ownership/permissions. Preserve the database comment: NIPAP uses it to identify
   its schema version. PostgreSQL roles are not included by `pg_dump`.
3. Adapt `/etc/nipap/nipap.conf` using the new configuration template and the source
   settings. Preserve authentication configuration and the web service account;
   set the destination database connection explicitly. Preserve suitable ownership
   and read access for the daemon and web server.
4. Check the restored database comment. For a standard 0.29.8 source, expect schema
   6. Rehearse the supplied 6 → 7 → 8 migrations on this restored copy, with the
   source server isolated from the destination's writes.
5. Check the SQLite authentication version with `nipap-passwd latest-version`.
   If an upgrade is required, back it up before `nipap-passwd upgrade-database`.

The PostgreSQL migration and SQLite authentication upgrade are separate operations.
Do not enable automatic schema creation on a migration destination.

PostgreSQL dump compatibility is documented at:
https://www.postgresql.org/docs/17/app-pgdump.html#APP-PGDUMP-NOTES

## Configure startup and the web server

After a successful restore, explicitly enable the tested schema upgrade procedure
for the destination if it is still on an older schema. In `/etc/default/nipapd`, use
`AUTO_INSTALL=no`, and set `AUTO_UPGRADE=yes` only for the planned schema upgrade.
Remove a legacy `RUN=no` setting or change it to `RUN=yes` before starting.

```sh
systemctl unmask nipapd.service
systemctl enable --now nipapd.service
systemctl status nipapd.service
journalctl -u nipapd.service -b
```

Once the schema upgrade is verified, set `AUTO_UPGRADE=no` again. The service runs
as `nipap:nipap`, with access to the `ssl-cert` group. Configure TLS and verify
certificate readability before allowing remote API access.

For the web interface, install Apache with Python 3 WSGI support:

```sh
apt install apache2 libapache2-mod-wsgi-py3
```

Configure a virtual host with:

```apache
WSGIScriptAlias / /etc/nipap/www/nipap-www.wsgi
<Directory /etc/nipap/www/>
    Require all granted
</Directory>
```

Configure HTTPS for the virtual host, check Apache's configuration, and reload it.
The web interface requires a trusted backend service account in `[www] xmlrpc_uri`
and a secret key. Reuse/adapt the restored settings. Ensure the web process can read
the required application and authentication configuration. Consult
`docs/config-www.rst` and `docs/audit-log.rst` in the release source for details.

Configure the CLI's `~/.nipaprc` with the destination server and a normal user.
Use mode `0600` if the file contains credentials.

## Acceptance and cutover

Verify prefix, pool, VRF and history data; user permissions; web login; CLI/API
operations; TLS; and startup after reboot. Test existing client integrations.

During final cutover, stop all source writes, take final database/authentication
backups, repeat the rehearsed restoration and upgrade, validate, then switch
clients. Keep the old server available. If the new server has accepted writes,
reconcile them before returning clients to the old installation.
