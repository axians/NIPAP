"""Administrator-only access to the historical IPAM audit trail."""
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from ipaddress import ip_network

import psycopg2
import pynipap
from psycopg2.extras import RealDictCursor
from flask import (
    Blueprint, abort, current_app, g, jsonify, render_template, request,
    session, url_for, redirect,
)

bp = Blueprint('audit', __name__, url_prefix='/audit')
PAGE_SIZE = 50
PAGE_SIZES = (25, 50, 100, 200)
FILTERS = ('username', 'vrf_id', 'prefix', 'prefix_id', 'from', 'to', 'before', 'page_size')


@bp.errorhandler(403)
def access_denied(error):
    message = ('You do not have access to the audit log. '
               'Please contact your NIPAP administrator to request access.')
    if request.endpoint == 'audit.entries':
        return jsonify(error=message), 403
    return render_template('audit_access_denied.html', message=message), 403


@bp.before_app_request
def set_audit_access():
    admins = {name.strip() for name in
              current_app.config.get('AUDIT_ADMINS', '').split(',') if name.strip()}
    g.audit_admin = bool(session.get('user') and
                         session.get('authenticated_identity') in admins)


def admin_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if not g.audit_admin:
            abort(403)
        return view(**kwargs)
    return wrapped


def build_query(filters, count=False):
    """Validate filters and keep all user input in bound parameters."""
    clauses = []
    try:
        page_size = int(filters.get('page_size') or PAGE_SIZE)
    except ValueError:
        raise ValueError('Entries per page must be 25, 50, 100 or 200') from None
    if page_size not in PAGE_SIZES:
        raise ValueError('Entries per page must be 25, 50, 100 or 200')
    params = {'limit': page_size + 1}
    for field in ('prefix_id', 'before'):
        value = filters.get(field)
        if value and not (count and field == 'before'):
            try:
                value = int(value)
            except ValueError:
                raise ValueError('{} must be an integer'.format(field)) from None
            if not 0 <= value <= 2147483647:
                raise ValueError('{} is outside the valid range'.format(field))
            params[field] = value
            clauses.append('id < %(before)s' if field == 'before' else
                           field + ' = %(' + field + ')s')
    if filters.get('vrf_id'):
        if len(filters['vrf_id']) > 4096:
            raise ValueError('VRF ID list is too long')
        try:
            vrf_ids = list(dict.fromkeys(int(value.strip()) for value in
                                        filters['vrf_id'].split(',') if value.strip()))
        except ValueError:
            raise ValueError('VRF IDs must be integers separated by commas') from None
        if not vrf_ids:
            raise ValueError('Enter at least one VRF ID or clear the VRF filter')
        if len(vrf_ids) > 50:
            raise ValueError('Enter no more than 50 VRF IDs')
        if any(not 0 <= value <= 2147483647 for value in vrf_ids):
            raise ValueError('VRF ID is outside the valid range')
        if len(vrf_ids) == 1:
            params['vrf_id'] = vrf_ids[0]
            clauses.append('vrf_id = %(vrf_id)s')
        else:
            params['vrf_ids'] = vrf_ids
            clauses.append('vrf_id = ANY(%(vrf_ids)s)')
    if filters.get('username'):
        if len(filters['username']) > 4096:
            raise ValueError('Username list is too long')
        usernames = list(dict.fromkeys(name.strip() for name in
                                       filters['username'].split(',') if name.strip()))
        if not usernames:
            raise ValueError('Enter at least one username or clear the user filter')
        if len(usernames) > 50:
            raise ValueError('Enter no more than 50 usernames')
        if any(len(name) > 255 for name in usernames):
            raise ValueError('Username is too long')
        if len(usernames) == 1:
            params['username'] = usernames[0]
            clauses.append('username = %(username)s')
        else:
            params['usernames'] = usernames
            clauses.append('username = ANY(%(usernames)s)')
    if filters.get('prefix'):
        try:
            params['prefix'] = str(ip_network(filters['prefix'], strict=False))
        except ValueError:
            raise ValueError('Enter a valid IPv4 or IPv6 prefix') from None
        clauses.append('prefix_prefix && %(prefix)s::cidr')
    for field in ('from', 'to'):
        if filters.get(field):
            try:
                day = date.fromisoformat(filters[field])
                value = datetime.combine(day, datetime.min.time(), timezone.utc)
                params[field] = value + timedelta(days=1) if field == 'to' else value
            except (ValueError, OverflowError):
                raise ValueError('Enter a valid date (YYYY-MM-DD)') from None
            clauses.append('timestamp >= %(from)s' if field == 'from' else
                           'timestamp < %(to)s')
    if 'from' in params and 'to' in params and params['from'] >= params['to']:
        raise ValueError('From date must not be after the to date')
    query = '''SELECT id, timestamp, username, authenticated_as,
                      authoritative_source, full_name, description,
                      vrf_id, vrf_rt, vrf_name, prefix_id,
                      prefix_prefix::text AS prefix, pool_id, pool_name
               FROM ip_net_log'''
    if count:
        query = 'SELECT COUNT(*) AS total FROM ip_net_log'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    return query if count else query + ' ORDER BY id DESC LIMIT %(limit)s', params


def read_entries(filters):
    query, params = build_query(filters)
    count_query, count_params = build_query(filters, count=True)
    page_size = params['limit'] - 1
    dsn = current_app.config.get('AUDIT_DB_DSN')
    if not dsn:
        abort(503, description='Audit database connection is not configured')
    connection = None
    try:
        connection = psycopg2.connect(dsn, connect_timeout=5)
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute(query, params)
                rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(count_query, count_params)
                total = cursor.fetchone()['total']
    except psycopg2.Error:
        # Do not expose database connection details in an HTTP response.
        abort(503, description='Audit log is temporarily unavailable')
    finally:
        if connection is not None:
            connection.close()
    next_before = rows[page_size - 1]['id'] if len(rows) > page_size else None
    rows = rows[:page_size]
    for row in rows:
        row['timestamp'] = row['timestamp'].astimezone(timezone.utc).isoformat()
    return rows, next_before, {
        'page_size': page_size, 'total_entries': total,
        'total_pages': (total + page_size - 1) // page_size,
    }


@bp.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/')
@admin_required
def index():
    filters = {key: request.args.get(key, '') for key in FILTERS}
    try:
        entries, next_before, totals = read_entries(filters)
    except ValueError as exc:
        return render_template('audit.html', page='audit', filters=filters,
                               entries=[], page_sizes=PAGE_SIZES, error=str(exc)), 400
    next_url = None
    if next_before is not None:
        next_url = url_for('audit.index', **dict(filters, before=next_before))
    return render_template('audit.html', page='audit', filters=filters,
                           entries=entries, next_url=next_url, page_sizes=PAGE_SIZES,
                           first_url=url_for('audit.index', **dict(filters, before='')),
                           **totals)


@bp.route('/vrf/<int:vrf_id>')
@admin_required
def open_vrf(vrf_id):
    try:
        vrfs = pynipap.VRF.list({'id': vrf_id})
    except pynipap.NipapError:
        abort(503, description='Unable to check whether this VRF still exists')
    if not vrfs:
        return render_template('audit_vrf_deleted.html', vrf_id=vrf_id), 404
    return redirect(url_for('ng.vrf') + '#/vrf/edit/{}'.format(vrf_id))


@bp.route('/prefix/<int:prefix_id>')
@admin_required
def open_prefix(prefix_id):
    try:
        prefixes = pynipap.Prefix.list({'id': prefix_id})
    except pynipap.NipapError:
        abort(503, description='Unable to check whether this prefix still exists')
    if not prefixes:
        return render_template('audit_prefix_deleted.html', prefix_id=prefix_id), 404
    return redirect(url_for('ng.prefix') + '#/prefix/edit/{}'.format(prefix_id))


@bp.route('/entries')
@admin_required
def entries():
    try:
        rows, next_before, totals = read_entries(request.args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(entries=rows, next_before=next_before, **totals)
