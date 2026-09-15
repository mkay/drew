#!/bin/bash
# Cut a release: bump versions, tag, push, build the Arch package, publish on
# GitHub and Forgejo, update the AUR. Ported from stenmark's release.sh minus
# what Drew doesn't have (what's-new dialog, .deb build).
set -euo pipefail

VERSION="${1:-}"
TITLE="${2:-}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: ./release.sh <version> [title]"
    echo "Example: ./release.sh 1.2.3"
    echo "Example: ./release.sh 1.2.3 \"Some Catchy Name\""
    exit 1
fi

# Strip leading 'v' if provided — version numbers in files are bare,
# git tag gets the v prefix
VERSION="${VERSION#v}"
TAG="v$VERSION"
TITLE="${TITLE:-$TAG}"

# Auto-detect project name from meson.build
PROJECT_NAME=$(grep -oP "^project\(\s*'\K[^']+" meson.build)
if [[ -z "$PROJECT_NAME" ]]; then
    echo "ERROR: Could not detect project name from meson.build"
    exit 1
fi

# Cleanup handler for temp directories
AUR_DIR=""
cleanup() {
    # Preserve the script's real exit status — the test below must not set it
    local status=$?
    [[ -n "$AUR_DIR" && -d "$AUR_DIR" ]] && rm -rf "$AUR_DIR"
    return $status
}
trap cleanup EXIT

echo "==> Releasing $PROJECT_NAME $TAG"

# 0. AppStream is where GNOME Software, KDE Discover and `flatpak info` read
# the version from — not from meson.build. An unmaintained <releases> block
# therefore makes every one of them name the wrong release, silently. Checked
# here so the entry is written before the tag rather than remembered after it.
METAINFO="data/de.singular.$PROJECT_NAME.metainfo.xml.in"
if [[ ! -f "$METAINFO" ]]; then
    echo "ERROR: $METAINFO not found — adjust the path in release.sh."
    exit 1
fi
METAINFO_VERSION=$(grep -oP '<release version="\K[^"]+' "$METAINFO" | head -1)
if [[ "$METAINFO_VERSION" != "$VERSION" ]]; then
    echo "ERROR: $METAINFO declares $METAINFO_VERSION as its newest release,"
    echo "       but this is $VERSION. Add a <release> entry for $VERSION,"
    echo "       or software centres will keep reporting $METAINFO_VERSION."
    exit 1
fi
if ! git diff --quiet -- "$METAINFO" || ! git diff --cached --quiet -- "$METAINFO"; then
    echo "ERROR: $METAINFO has uncommitted changes."
    echo "       release.sh won't include them in $TAG. Commit them first."
    exit 1
fi

# 1. Update version in meson.build and PKGBUILD. drew/__init__.py is
# generated from __init__.py.in at build time, so meson.build is the only
# place the Python side reads the version from.
sed -i "0,/version: '[^']*'/{s/version: '[^']*'/version: '$VERSION'/}" meson.build
sed -i "s/^pkgver=.*/pkgver=$VERSION/" PKGBUILD
# pkgrel counts rebuilds of one pkgver, so a new version restarts it at 1.
sed -i "s/^pkgrel=.*/pkgrel=1/" PKGBUILD
# PKGBUILD.local isn't released and isn't tracked, so it is bumped but never
# committed: a stale pkgver makes local test installs report the wrong
# version to pacman. It's absent in a fresh clone, hence the test.
if [[ -f PKGBUILD.local ]]; then
    sed -i "s/^pkgver=.*/pkgver=$VERSION/" PKGBUILD.local
    sed -i "s/^pkgrel=.*/pkgrel=1/" PKGBUILD.local
fi

# 2. Generate the changelog for the forge releases
PREV_TAG=$(git tag --sort=-version:refname | head -1)
if [[ -n "$PREV_TAG" ]]; then
    RELEASE_NOTES=$(git log --pretty=format:"- %s" "$PREV_TAG..HEAD" | grep -v -E "^- (Release |PKGBUILD: checksum)")
else
    RELEASE_NOTES=$(git log --pretty=format:"- %s" | grep -v -E "^- (Release |PKGBUILD: checksum)")
fi
echo "==> Release notes:"
echo "$RELEASE_NOTES"

# 3. Commit (if there are changes) and tag
git add meson.build PKGBUILD
if ! git diff --cached --quiet; then
    git commit -m "Release $TAG"
else
    echo "==> Version already set to $VERSION, skipping commit"
fi
git tag -a "$TAG" -m "Release $TAG"

# 4. Push commit and tag. origin carries both push URLs (Forgejo and
# GitHub), so one push reaches both.
for remote in $(git remote); do
    echo "==> Pushing to $remote"
    git push "$remote" HEAD "$TAG"
done

# 5. Build Arch package
echo "==> Updating checksums"
# GitHub needs a moment to generate the tarball after the tag push — and the
# download itself takes a few seconds, so give it a generous window. Aborting
# here is far better than building against a stale checksum.
CHECKSUMS_OK=0
for _attempt in $(seq 1 10); do
    if updpkgsums; then
        CHECKSUMS_OK=1
        break
    fi
    echo "==> Tarball not ready yet (attempt $_attempt/10), retrying in 15s..."
    sleep 15
done
if [[ "$CHECKSUMS_OK" -ne 1 ]]; then
    echo "ERROR: updpkgsums never succeeded — the release tarball for $TAG is not"
    echo "       downloadable yet. The tag is already pushed, so re-run:"
    echo "         git checkout PKGBUILD && git tag -d $TAG"
    echo "         ./release.sh $VERSION \"$TITLE\""
    exit 1
fi
echo "==> Building Arch package"
makepkg -sf --noconfirm
# makepkg --packagelist prints the exact paths this PKGBUILD produces,
# honouring pkgrel, PKGEXT and PKGDEST. A glob over the repo root would
# happily pick a package left over from an earlier release instead.
ARCH_PKG=$(makepkg --packagelist | grep -v -- '-debug-' | head -1)
if [[ ! -f "$ARCH_PKG" ]]; then
    echo "ERROR: makepkg did not produce $ARCH_PKG"
    exit 1
fi

# Push updated checksums back to repos
if ! git diff --quiet PKGBUILD; then
    git add PKGBUILD
    git commit -m "PKGBUILD: checksum for the $TAG tarball"
    for remote in $(git remote); do
        git push "$remote" HEAD
    done
fi

# 6. Create releases
RELEASE_ASSETS=("$ARCH_PKG")

# GitHub release — the GitHub repo is one of origin's push URLs, so look
# at those rather than at the fetch URL.
GH_REPO=""
for url in $(git remote get-url --push --all origin); do
    if echo "$url" | grep -q github.com; then
        GH_REPO=$(echo "$url" | sed 's|.*github.com[:/]||;s|\.git$||')
        break
    fi
done
if [[ -n "$GH_REPO" ]] && command -v gh &>/dev/null; then
    echo "==> Creating GitHub release ($GH_REPO)"
    gh release create "$TAG" "${RELEASE_ASSETS[@]}" \
        --repo "$GH_REPO" \
        --title "$TITLE" \
        --notes "$RELEASE_NOTES"
    echo "==> GitHub release created"
fi

# Forgejo release via API — the fetch URL is the Forgejo one
FORGEJO_URL=""
REPO_PATH=""
url=$(git remote get-url origin)
if [[ "$url" =~ ^ssh://[^@]+@([^/:]+)[:/](.+)$ ]]; then
    FORGEJO_URL="${BASH_REMATCH[1]}"
    REPO_PATH="${BASH_REMATCH[2]%.git}"
elif [[ "$url" =~ ^[^@]+@([^:]+):(.+)$ ]]; then
    FORGEJO_URL="${BASH_REMATCH[1]}"
    REPO_PATH="${BASH_REMATCH[2]%.git}"
fi

# The token is only needed for the two API calls below, so it is fetched here
# rather than exported from a shell profile: an exported secret sits in the
# environment of every process started from that shell, where any stray `echo`
# or crash dump can spill it. Kept in the login keyring, like gh's own token:
#   secret-tool store --label='Forgejo release token' service forgejo host git.singular.de
# An already-set FORGEJO_TOKEN still wins, so a one-off run can override it.
if [[ -z "${FORGEJO_TOKEN:-}" && -n "$FORGEJO_URL" ]] && command -v secret-tool &>/dev/null; then
    FORGEJO_TOKEN=$(secret-tool lookup service forgejo host "$FORGEJO_URL" 2>/dev/null || true)
fi
# A missing token used to skip the Forgejo release in silence, which is how a
# release ends up published in one place and not the other.
if [[ -n "$FORGEJO_URL" && -z "${FORGEJO_TOKEN:-}" ]]; then
    echo "WARNING: no FORGEJO_TOKEN and none in the keyring for $FORGEJO_URL —"
    echo "         skipping the Forgejo release. The tag and its pushes are unaffected."
fi

if [[ -n "$FORGEJO_URL" && -n "${FORGEJO_TOKEN:-}" ]]; then
    echo "==> Creating Forgejo release on $FORGEJO_URL ($REPO_PATH)"

    # Check if release already exists for this tag
    EXISTING=$(curl -s "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/tags/$TAG" \
        -H "Authorization: token $FORGEJO_TOKEN")
    EXISTING_ID=$(echo "$EXISTING" | jq -r '.id // empty')

    if [[ -n "$EXISTING_ID" ]]; then
        echo "==> Release for $TAG already exists (id=$EXISTING_ID), deleting..."
        curl -s -X DELETE "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/$EXISTING_ID" \
            -H "Authorization: token $FORGEJO_TOKEN"
    fi

    COMMIT_SHA=$(git rev-parse HEAD)
    RELEASE_JSON=$(curl -s -X POST "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases" \
        -H "Authorization: token $FORGEJO_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg tag "$TAG" --arg title "$TITLE" --arg body "$RELEASE_NOTES" --arg sha "$COMMIT_SHA" \
            '{tag_name: $tag, name: $title, body: $body, target_commitish: $sha}')")

    RELEASE_ID=$(echo "$RELEASE_JSON" | jq -r '.id')

    if [[ "$RELEASE_ID" != "null" && -n "$RELEASE_ID" ]]; then
        for asset in "${RELEASE_ASSETS[@]}"; do
            echo "==> Uploading $asset to Forgejo"
            curl -s -X POST "https://$FORGEJO_URL/api/v1/repos/$REPO_PATH/releases/$RELEASE_ID/assets" \
                -H "Authorization: token $FORGEJO_TOKEN" \
                -F "attachment=@$asset"
        done
        echo "==> Forgejo release created"
    else
        echo "WARNING: Failed to create Forgejo release"
        echo "$RELEASE_JSON"
    fi
fi

# 7. Push to AUR
echo "==> Pushing to AUR"
makepkg --printsrcinfo > .SRCINFO
AUR_DIR=$(mktemp -d)
git clone ssh://aur@aur.archlinux.org/"$PROJECT_NAME".git "$AUR_DIR"
cp PKGBUILD .SRCINFO "$AUR_DIR"/
cd "$AUR_DIR"
git checkout master 2>/dev/null || git checkout -b master
git add PKGBUILD .SRCINFO
git commit -m "Update to $VERSION"
git push origin master
cd - >/dev/null
rm -rf "$AUR_DIR"
AUR_DIR=""
echo "==> AUR updated"

echo ""
echo "==> Done! Released $PROJECT_NAME $TAG"
