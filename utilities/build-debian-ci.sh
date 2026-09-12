#!/bin/bash
# Build Debian source and binary packages without pip or undeclared build deps.
set -euo pipefail

project=${1:?Usage: build-debian-ci.sh PROJECT OUTPUT_DIRECTORY}
mode=${3:-build}
case "$mode" in
    build|--source-only) ;;
    *) echo 'Optional third argument must be --source-only' >&2; exit 2 ;;
esac
case "$project" in
    nipap|pynipap|nipap-cli|nipap-www|whoisd) ;;
    *) echo "Unknown project: $project" >&2; exit 2 ;;
esac
repo=$(cd "$(dirname "$0")/.." && pwd)
output=$(realpath -m "${2:?Output directory required}")
case "$output/" in
    "$repo/$project/"*) echo 'Output must be outside the project source' >&2; exit 2 ;;
esac
mkdir -p "$output"
exec > >(tee "$output/build.log") 2>&1
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

source_name=$(dpkg-parsechangelog -l "$repo/$project/debian/changelog" -S Source)
version=$(dpkg-parsechangelog -l "$repo/$project/debian/changelog" -S Version)
upstream=${version#*:}
upstream=${upstream%-*}
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(dpkg-parsechangelog -l "$repo/$project/debian/changelog" -S Timestamp)
source_dir="$work/$source_name-$upstream"
mkdir "$source_dir"
# The checkout is the source of truth. Exclude local build products, not sources.
exclude_packages=()
while IFS= read -r binary_package; do
    exclude_packages+=("--exclude=./debian/$binary_package")
done < <(sed -n 's/^Package: //p' "$repo/$project/debian/control")
tar -C "$repo/$project" --exclude-vcs --exclude='./.pybuild' \
    --exclude='./build' --exclude='./dist' --exclude='*.egg-info' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='./.pc' \
    --exclude='./debian/tmp' --exclude='./debian/.debhelper' \
    --exclude='./debian/files' --exclude='./debian/*.substvars' \
    --exclude='./debian/*debhelper*' "${exclude_packages[@]}" \
    -cf - . | tar -xf - -C "$source_dir"

tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 \
    --numeric-owner -C "$work" --exclude="$source_name-$upstream/debian" \
    -cJf "$work/${source_name}_${upstream}.orig.tar.xz" "$source_name-$upstream"
(cd "$work" && dpkg-source -b "$source_dir")
cp "$work/"*.dsc "$work/"*.tar.* "$output/"
if [ "$mode" = --source-only ]; then
    exit 0
fi

cat > "$work/pbuilderrc" <<EOF
DISTRIBUTION=trixie
MIRRORSITE=https://deb.debian.org/debian
COMPONENTS=main
BUILDUSERID=1234
BUILDUSERNAME=pbuilder
EOF
printf 'BUILDRESULT=%q\n' "$output" >> "$work/pbuilderrc"

base_tgz=${DEBIAN_BASE_TGZ:-$work/trixie-base.tgz}
if [ ! -f "$base_tgz" ]; then
    pbuilder create --configfile "$work/pbuilderrc" \
        --basetgz "$base_tgz" --distribution trixie \
        --architecture amd64 --mirror https://deb.debian.org/debian \
        --debootstrapopts --variant=buildd
fi
pbuilder build --configfile "$work/pbuilderrc" \
    --basetgz "$base_tgz" --buildresult "$output" \
    --use-network no --debbuildopts '-b -us -uc' "$work/"*.dsc

(cd "$output" && sha256sum ./*.deb ./*.dsc ./*.tar.* ./*.changes ./*.buildinfo > SHA256SUMS)
