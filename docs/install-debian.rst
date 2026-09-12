Getting started for sysadmins
-----------------------------
Debian 13 (trixie)
=================

For a local database, install PostgreSQL and its matching ip4r extension::

    sudo apt install postgresql postgresql-17-ip4r

Build the backend packages from this checkout using Debian's build tools::

    sudo apt install build-essential debhelper dh-python python3-all python3-setuptools python3-docutils pybuild-plugin-pyproject
    cd nipap
    dpkg-buildpackage -b -us -uc

The backend requires ``python3-flask-restx`` and ``python3-flask-xml-rpc-re``,
which are available from NIPAP's testing repository rather than Debian 13's
own repositories. Configure that repository using a dedicated signing key::

    sudo apt install ca-certificates curl
    curl -fsSLo /tmp/nipap.asc https://spritelink.github.io/NIPAP/nipap.gpg.key
    sudo install -m 0644 /tmp/nipap.asc /usr/share/keyrings/nipap.asc
    echo 'deb [signed-by=/usr/share/keyrings/nipap.asc] https://spritelink.github.io/NIPAP/repos/apt testing main extra' | sudo tee /etc/apt/sources.list.d/nipap.list
    sudo apt update
    sudo apt install ../nipap-common_*.deb ../nipapd_*.deb

Select local database configuration and automatic startup during installation.
Automatic schema upgrades remain an explicit administrator choice. The custom
systemd changes described below are in the packages built from this checkout;
they are not implied to exist in the published repository packages.

The package supplies ``nipapd.service``. It starts the daemon as ``nipap:nipap``
with ``SupplementaryGroups=ssl-cert``, runs in the foreground without a PID
file, and logs to the journal. Matching ``user = nipap`` and ``group = nipap``
settings in ``nipap.conf`` are accepted without clearing those groups.

``/etc/default/nipapd`` controls ``AUTO_INSTALL`` and ``AUTO_UPGRADE``.
New installations use systemd to enable or disable startup. An existing
``RUN=no`` from an older package is still honored; remove that legacy setting
or set it to ``yes`` before enabling the service. Upgrades preserve existing
settings; ``dpkg-reconfigure nipapd`` reapplies the debconf choices.
Use systemctl to manage the service::

    sudo systemctl enable --now nipapd
    sudo systemctl status nipapd
    sudo journalctl -u nipapd -b

TLS certificate access
~~~~~~~~~~~~~~~~~~~~~~

Install the certificate chain at ``/etc/ssl/certs/nipap.crt`` and its private
key at ``/etc/ssl/private/nipap.key``. Give the key group read access::

    sudo chown root:ssl-cert /etc/ssl/private/nipap.key
    sudo chmod 0640 /etc/ssl/private/nipap.key

Every parent directory, including symlink targets, must permit traversal by
the service. Group membership alone does not grant access to root-only files.
Configure the existing ``[nipapd]`` section in ``/etc/nipap/nipap.conf``::

    ssl_port = 1338
    ssl_cert_file = /etc/ssl/certs/nipap.crt
    ssl_key_file = /etc/ssl/private/nipap.key
    syslog = false

Keep ``listen = 127.0.0.1`` for local access, or explicitly choose the server's
listening addresses. Set ``port =`` (empty) to disable plaintext HTTP.
Restart the service after installing or renewing a certificate::

    sudo systemctl restart nipapd

There is no certificate reload via SIGHUP. The service deliberately has no
``ExecReload`` action. An unreadable key or invalid certificate is reported in
the journal before database setup or worker creation.

Older releases
==============

The following instructions describe the historical packages and installation
flow. Use the Debian 13 instructions above for trixie.

This guide will walk you through the setup process to get NIPAP up and running
on a Debian 7.0 (wheezy) or Ubuntu 12.04 or later system. With no prior
experience it should take about 15 minutes.

Debian and Debian derivatives (primarily Ubuntu) are the only distributions
supported at this time. It is certainly possible to install on other Linux
flavours or other UNIX-style operating systems, but there are no prebuilt
packages. Please see `install-unix <install-unix.rst>`_ for installation
instructions on non-Debian like Unix systems.

Debian installation
-------------------
Start by installing PostgreSQL, the contrib package and the ip4r extension.
Depending on which Debian or Ubuntu release you are running, different versions
are available. Anything after PostgreSQL 9.0 will do. Make sure you install
ip4r and the contrib package for your version of Postgres or if this is a fresh
install you can specify the version you want of ip4r and it will pull in the
same version of postgresql::

    root@debian:~# apt-cache search ip4r
    postgresql-9.1-ip4r - IPv4 and IPv6 types for PostgreSQL 9.1
    postgresql-8.4-ip4r - IPv4 and IPv4 range index types for PostgreSQL 8.4
    root@debian:~# apt-cache search postgres contrib
    postgresql-contrib-9.1 - additional facilities for PostgreSQL
    root@debian:~# apt-get install postgresql-9.1-ip4r postgresql-contrib-9.1

Add the NIPAP repo to your package sources, add our public key for proper
authentication of our packages and update your lists::

    echo "deb http://spritelink.github.io/NIPAP/repos/apt stable main extra" | sudo tee /etc/apt/sources.list.d/nipap.list
    wget -O - https://spritelink.github.io/NIPAP/nipap.gpg.key | sudo apt-key add -
    sudo apt-get update

There are now five new packages::

    root@debian:~# apt-cache search nipap
    nipap-cli - Neat IP Address Planner
    nipap-common - Neat IP Address Planner
    nipap-www - web frontend for NIPAP
    nipapd - Neat IP Address Planner XML-RPC daemon
    python-pynipap - Python module for accessing NIPAP
    root@debian:~#

The 'nipapd' package contains the XML-RPC backend daemon which is a required
component of the NIPAP system. It essentially represents the content of the
database over an XML-RPC interface, allowing additions, deletions and
modifications. 'nipap-common' is a library with common stuff needed by all the
other components, so regardless which one you choose, you will get this one.
'nipap-cli' is, not very surprisingly, a CLI client for NIPAP while 'nipap-www'
is the web GUI. Choose your favourite interface or both and install it, you
will automatically get 'python-pynipap' which is the client-side library for
Python applications and since both the web GUI and CLI client is written in
Python, you will need 'python-pynipap'. If you want, you can install the nipapd
backend on one machine and the CLI and/or web on another.

Let's install the backend::

    sudo apt-get install nipapd

During installation, the nipapd package will ask if you want to automatically
load the needed database structure and start nipapd on startup - answer Yes to
both questions. After the installation is done, you will have the PostgreSQL
database server and all the other necessary dependencies installed.


Web UI
------
The nipap-www package comes with an automagic configuration guide that will
help you setup the needed user and configure it if, and only if, you are
running nipapd on the same machine. Install nipap-www with::

    sudo apt-get install nipap-www

When you are asked whether you want to add a user automatically and configure
it, answer yes. If you tried to install nipap-www at the same time as nipapd,
you might not be prompted with the quetion to automatically add a user. Try
doing 'sudo dpkg-reconfigure nipap-www' in the case.

The user added to the local authentication database by the installation script
is merely used by the web interface to talk to the backend.

See `config-www <config-www.rst>`_ for configuration of the web UI and how to
serve it using a web server.
