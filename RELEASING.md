# Release Checklist

Releases are published to PyPI automatically by
`.github/workflows/publish.yml` when a `v*` tag is pushed. The tag push
runs tests and lint first; publishing only happens if both pass.

The package version is **derived from the git tag** by
[setuptools-scm](https://setuptools-scm.readthedocs.io/) — there is no
version string to edit in `pyproject.toml`. Untagged builds get a dev
version such as `1.2.1.dev6+g1630c8c`. Check what will be built with
`python -m setuptools_scm`.

## 1. Pre-flight

- [ ] On `main`, up to date with `origin/main`, clean working tree
      (`git status`, `git pull`)
- [ ] All intended PRs (including Dependabot) are merged
- [ ] Full local check passes in the venv:
      ```bash
      make test          # format + lint + mypy --strict (src/tests/examples) + pytest --cov
      ruff format --check src/ tests/
      ```
- [ ] If protocol/device behaviour changed, verify against a real Glow
      (e.g. `examples/`, `debug/` scripts) and update `CLAUDE.md`
      design notes if new protocol facts were learned

## 2. Choose the version (SemVer)

- [ ] Review changes since the last tag:
      `git log --oneline $(git describe --tags --abbrev=0)..HEAD`
- [ ] **MAJOR** — breaking public API change (e.g. 1.0.0: merged
      `set_brightness`/`set_dimming_time` into one method)
- [ ] **MINOR** — new features / backward-compatible API changes
      (new constants, new fields with compat properties, behaviour
      changes callers may need to adapt to)
- [ ] **PATCH** — bug fixes only

## 3. Release commit

- [ ] `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)):
  - [ ] Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
        (or add the section if there is no Unreleased one)
  - [ ] Entries grouped under `Added` / `Changed` / `Fixed` / `Removed`
  - [ ] Breaking changes and required caller migrations called out in **bold**
  - [ ] **Add the compare link at the bottom** (often forgotten — see
        `d5ad524`, `aa61b16`):
        ```
        [X.Y.Z]: https://github.com/mikeodr/pycasperglow/compare/vPREV...vX.Y.Z
        ```
- [ ] Commit the changelog:
      ```bash
      git add CHANGELOG.md
      git commit -m "chore: release X.Y.Z"
      ```

## 4. Tag and publish

- [ ] Create an annotated tag on the release commit (this *sets* the
      version):
      ```bash
      git tag -a vX.Y.Z -m "Release vX.Y.Z"
      python -m setuptools_scm   # must print exactly X.Y.Z
      ```
- [ ] Push the commit, then the tag:
      ```bash
      git push origin main
      git push origin vX.Y.Z
      ```
- [ ] Watch the **Publish to PyPI** workflow (`test` → `lint` → `publish`)
      to completion; approve the `pypi` environment if prompted

## 5. Post-release

- [ ] Confirm the new version on https://pypi.org/project/pycasperglow/
- [ ] (Optional) Create a GitHub Release from the tag using the
      CHANGELOG section as notes
- [ ] Bump the `pycasperglow==X.Y.Z` requirement in the Home Assistant
      `casper_glow` integration `manifest.json` if needed
- [ ] Add a fresh `## [Unreleased]` section to `CHANGELOG.md` for the
      next cycle

## If something goes wrong

- Publish job failed before upload: fix on `main`, then delete and
  re-create the tag (`git tag -d vX.Y.Z && git push --delete origin vX.Y.Z`).
- Already uploaded to PyPI: versions can't be re-used — release a new
  PATCH version instead.
