Debian 13 package builds
=======================

The ``Debian 13 packages`` GitHub Actions workflow builds all five source
projects: ``nipap``, ``pynipap``, ``nipap-cli``, ``nipap-www`` and ``whoisd``.
The backend source produces two binaries, ``nipapd`` and ``nipap-common``.

It runs on pull requests, pushes to ``master`` or ``deb13-*`` branches,
``v*`` tags, and manual dispatch. No package is published to an APT repository
or a GitHub release. The workflow only needs read access to repository content.

Each matrix job uses Debian trixie's packaging tools and a fresh pbuilder
chroot. Build dependencies are installed from ``debian/control``. Compilation
runs as an unprivileged build user with networking disabled; pip downloads and
undeclared dependencies cannot silently make a build succeed. The outer
container needs privileged mode to create pbuilder's mount/network namespaces.

The build creates a ``3.0 (quilt)`` source package with an upstream tarball,
a Debian tarball and a ``.dsc`` descriptor. pbuilder builds binaries from that
source package. The artifacts include:

* ``.deb`` packages
* ``.dsc``, ``.orig.tar.xz`` and ``.debian.tar.xz`` source files
* ``.changes`` and ``.buildinfo`` build metadata
* ``SHA256SUMS``, ``build.log`` and ``lintian.log``

Lintian checks source and binary packages with the Debian profile. Errors fail
the job, including when a package contains a Lintian override. Warnings and
informational findings remain visible in the log. Artifacts are retained for
30 days even after a failed check so the failure can be investigated; a failed
job's artifacts must not be treated as validated release packages.

These are unsigned CI artifacts. Archive acceptance, signing and package
publication are separate release steps; Lintian is an automated check, not a
complete certification of Debian Policy compliance.

Local reproduction
------------------

On a disposable Debian 13 build machine, install ``pbuilder``, ``debootstrap``,
``debian-archive-keyring``, ``dpkg-dev``, ``lintian``, ``ca-certificates`` and
``xz-utils``. From the checkout, run::

    sudo bash utilities/build-debian-ci.sh nipap /tmp/nipap-debian-artifacts
    lintian --profile debian --fail-on error --display-info --no-override /tmp/nipap-debian-artifacts/*.dsc /tmp/nipap-debian-artifacts/*.changes

Replace ``nipap`` with any matrix project. To prepare just the source package,
add ``--source-only`` as a third argument. For repeated local builds,
``DEBIAN_BASE_TGZ`` may point to a previously created, trusted trixie amd64 base
tarball. Each build still unpacks a separate clean chroot; CI always creates a
new base image.

The checks follow the interfaces documented in Debian's
`pbuilder manual <https://manpages.debian.org/trixie/pbuilder/pbuilder.8.en.html>`_
and `Lintian manual <https://manpages.debian.org/trixie/lintian/lintian.1.en.html>`_.
