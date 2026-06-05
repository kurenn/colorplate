# Releasing ColorPlate

Releases are **tag-driven**. Pushing a `v*` tag runs
[`.github/workflows/release.yml`](.github/workflows/release.yml), which:

1. **Builds** the sdist + wheel and validates them with `twine check`.
2. **Verifies** the tag matches `project.version` in `pyproject.toml` (fails fast otherwise).
3. **Creates a GitHub Release** with notes pulled from the matching `CHANGELOG.md` section and the built artifacts attached.
4. **Publishes a container image** to GHCR: `ghcr.io/kurenn/colorplate:<version>` (+ `:<major>.<minor>` and `:latest`).
5. **Publishes to PyPI** via Trusted Publishing — *once enabled* (see below).

## Cutting a release

```bash
# 1. Bump the version + changelog (must match the tag you'll push)
#    - pyproject.toml  ->  project.version = "X.Y.Z"
#    - CHANGELOG.md    ->  move items from [Unreleased] into a new [X.Y.Z] section + date,
#                          and add the compare/tag link lines at the bottom.

# 2. Commit on a branch, open a PR, merge to main.

# 3. Tag main and push — this triggers the release:
git checkout main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

Versioning follows [SemVer](https://semver.org/). Pre-release tags
(e.g. `v0.2.0-rc.1`) are auto-marked as *pre-release* and skip the `:latest`
Docker tag.

> **Tip:** the version-match guard means the tag is the single source of truth —
> if `pyproject.toml` and the tag disagree, the build fails before anything ships.

## One-time: enable PyPI publishing

The workflow uses **Trusted Publishing** (OIDC) — no API tokens are stored.
Until it's configured, the `pypi` job is skipped (the rest of the release still runs).

1. On [PyPI](https://pypi.org/manage/account/publishing/), add a **pending publisher**:
   - Project name: `colorplate`
   - Owner: `kurenn`
   - Repository: `colorplate`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. In this repo: **Settings → Secrets and variables → Actions → Variables**, add
   a repository variable `PUBLISH_TO_PYPI` = `true`.
3. (Optional) Add an `pypi` **Environment** under Settings → Environments with
   required reviewers if you want a manual gate before each upload.

The next `v*` tag will then publish to PyPI automatically.

## Container image

The GHCR image is public-or-private per your package settings. Pull it with:

```bash
docker pull ghcr.io/kurenn/colorplate:latest
docker run -p 8000:8000 ghcr.io/kurenn/colorplate:latest   # http://localhost:8000
```

> Render deploys from the `Dockerfile` via its own Blueprint (`render.yaml`), so
> the GHCR image is for anyone who wants to run the published container directly —
> it does not change the Render pipeline.
