#!/usr/bin/env bash

set -euo pipefail

release_kind="${1:-}"
version="${2:-}"

usage() {
    cat <<'EOF'
Usage:
  make rc VERSION=0.1.0rc1
  make release VERSION=0.1.0

The command creates a release branch from a clean, up-to-date main branch,
updates the project version, runs checks, pushes only the release branch, and
opens a pull request. It never pushes main or creates a release tag. Merging
the pull request authorizes the release workflow to create the tag and publish.
EOF
}

if [[ -z "$version" ]]; then
    usage >&2
    exit 2
fi

case "$release_kind" in
    rc)
        if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+rc[1-9][0-9]*$ ]]; then
            printf 'RC version must look like 0.1.0rc1: %s\n' "$version" >&2
            exit 2
        fi
        release_label="release candidate"
        ;;
    stable)
        if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            printf 'Stable version must look like 0.1.0: %s\n' "$version" >&2
            exit 2
        fi
        release_label="stable release"
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

if ! command -v gh >/dev/null 2>&1; then
    printf '%s\n' 'GitHub CLI (gh) is required to open the release pull request.' >&2
    exit 1
fi

if ! repository="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"; then
    printf '%s\n' \
        'GitHub CLI must be authenticated for this repository. Run: gh auth login' >&2
    exit 1
fi
image_repository="ghcr.io/$(printf '%s' "$repository" | tr '[:upper:]' '[:lower:]')"

if [[ "$(git branch --show-current)" != "main" ]]; then
    printf '%s\n' 'Release pull requests must be created from the main branch.' >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    printf '%s\n' 'The working tree must be clean before preparing a release.' >&2
    exit 1
fi

printf '%s\n' 'Fetching main and existing tags from origin...'
git fetch origin main --tags

if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
    printf '%s\n' 'Local main must exactly match origin/main before preparing a release.' >&2
    exit 1
fi

tag="v${version}"
branch="release/${tag}"

current_version="$(uv version --short)"
if [[ "$current_version" = "$version" ]]; then
    printf 'Project version is already %s; no release PR change is needed.\n' \
        "$version" >&2
    exit 1
fi

if git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null; then
    printf 'Tag already exists: %s\n' "$tag" >&2
    exit 1
fi

if git show-ref --verify --quiet "refs/heads/${branch}" \
    || git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    printf 'Release branch already exists: %s\n' "$branch" >&2
    exit 1
fi

printf 'Creating %s pull request for %s...\n' "$release_label" "$tag"
git switch --create "$branch"
uv version "$version" --no-sync

if git diff --quiet -- pyproject.toml uv.lock; then
    printf 'Project version is already %s; no release PR change was produced.\n' \
        "$version" >&2
    exit 1
fi

uv sync --locked
uv run pre-commit run --all-files
make no-hw-test

if ! git diff --quiet -- . \
    ':(exclude)pyproject.toml' \
    ':(exclude)uv.lock'; then
    printf '%s\n' 'Checks changed files other than version metadata; review them first.' >&2
    exit 1
fi

if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    printf '%s\n' 'Checks created untracked files; review them first.' >&2
    exit 1
fi

git add pyproject.toml uv.lock
git commit --message "Prepare ${tag}"
git push --set-upstream origin "$branch"

pr_body="$({
    printf '## Release\n\n'
    printf -- '- Type: %s\n' "$release_label"
    printf -- '- Project version: `%s`\n' "$version"
    printf -- '- Expected Git tag: `%s`\n' "$tag"
    printf -- '- Expected image: `%s:%s-bookworm`\n\n' \
        "$image_repository" "$version"
    printf '%s\n' 'Merging this PR authorizes the release workflow to create the tag and publish the release artifacts.'
})"

if ! gh pr create \
    --base main \
    --head "$branch" \
    --title "Prepare ${tag}" \
    --body "$pr_body"; then
    printf '%s\n' \
        'The branch was pushed, but GitHub CLI could not create the pull request.' \
        "Retry with: gh pr create --base main --head ${branch}" >&2
    exit 1
fi

git switch main
printf '%s\n' \
    "Opened the ${tag} release pull request." \
    'Merge it after CI passes; no tag or main-branch push was made locally.'
