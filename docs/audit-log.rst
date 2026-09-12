Web audit log
=============

The audit log records IPAM changes from ``ip_net_log``, including the user,
authenticated account, source, timestamp and historical object values. It does
not display daemon or system logs. Deleted prefixes, pools and VRFs remain in
the history. Prefix and VRF links open the current object. Deleted objects show a message
with a link to their audit history.

Access is disabled by default. NIPAP has no general administrator role; enable
this feature for explicit authenticated identities in ``nipap.conf``::

    [www]
    audit_admins = admin@local
    audit_db_dsn = host=localhost dbname=nipap user=nipap_audit password=CHANGE_ME sslmode=require

Use comma-separated ``username@backend`` identities. The backend suffix is
required even when users normally log in without it. Authorization uses the
authenticated identity saved at login, not the delegated username or the web
service's API account. Users must log in again after installing this feature.
Restart the web application after changing the allowlist. Both ``/audit/`` and
``/audit/entries`` reject everyone outside the allowlist with HTTP 403.

The web application connects directly to PostgreSQL for this read-only feature.
It can connect to a remote database; configure network access and TLS accordingly.
Create a dedicated database role using an administrator connection to the NIPAP
database, and set its password with psql's ``\password nipap_audit`` command::

    CREATE ROLE nipap_audit LOGIN;
    GRANT CONNECT ON DATABASE nipap TO nipap_audit;
    GRANT USAGE ON SCHEMA public TO nipap_audit;
    GRANT SELECT ON public.ip_net_log TO nipap_audit;

Store the connection string in the protected web configuration. The role needs
no access to other tables or sequences and no write permissions. Queries also
run in a read-only transaction with a five-second statement timeout.

Open **audit log** in the navigation bar. Filter by exact usernames, VRF ID,
overlapping IPv4/IPv6 prefix, prefix ID or inclusive UTC date range. Results show
25, 50, 100 or 200 entries per page (50 by default), with matching entry and
page totals. Entries are ordered by decreasing audit ID; **Older entries** continues
from the last ID without offset pagination. Refresh the first page to see new
changes. The global VRF selector does not affect this page; use its VRF ID filter.
Separate usernames with commas to include entries from any of those users
(for example, ``admin, markus``). Matching is case-sensitive, with no wildcards.
Leave the user filter empty to include all users. Up to 50 usernames are allowed;
surrounding spaces and duplicate names are ignored.
VRF IDs also accept a comma-separated list, such as ``0, 2, 5``, with up to
50 IDs. Leave this filter empty to include all VRFs. When both filters are
set, entries must match one of the selected users and one of the selected VRFs.
Descriptions are displayed as escaped text, never evaluated as Python or HTML.

Run the focused tests with the web and backend dependencies installed::

    PYTHONPATH=nipap-www:nipap:pynipap python3 -m unittest discover -s tests -p test_web_audit.py
