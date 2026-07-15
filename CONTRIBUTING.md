# Contributing to MReyeXtract

Thanks for your interest in improving MReyeXtract! It is maintained as part of
the OpenMReye ecosystem and depended on by other packages, so we keep the
contribution process lightweight but disciplined. Releases are automated
directly from your pull request, so please read this before contributing.

## Getting started

For anything larger than a small fix, please **open an issue first** so we can
agree on the approach before you invest time. Questions are welcome at
z.b.nudelman[at]vu.nl or m.nau[at]vu.nl.

## Development setup

MReyeXtract targets **Python 3.11**. Install an editable checkout with the
development extras:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If ANTsPy has no wheel for your platform, install it first (see the
[ANTsPy guide](https://github.com/ANTsX/ANTsPy)) and re-run the install.

## Before you open a PR

Run the same checks CI enforces, and add tests for any new behavior:

```bash
./format_and_test.sh      # black, mypy, pylint, pytest
```

- **Style:** `black` formats the code and `pylint` + `mypy` must pass.
- **Tests:** new features and bug fixes need tests; keep the suite green.
- Keep PRs focused — one logical change per PR is much easier to review.

## Pull request workflow

`main` is protected: no direct pushes. All changes land through pull requests
that are **squash-merged**, so **your PR title becomes the commit message on
`main`** — and that title drives the automatic version bump. It **must** be a
valid [Conventional Commit](https://www.conventionalcommits.org/):

| PR title prefix | Example | Release effect |
| --- | --- | --- |
| `fix:` | `fix: correct mask resampling origin` | patch (`0.1.0` → `0.1.1`) |
| `feat:` | `feat: add --as-pickle output` | minor (`0.1.0` → `0.2.0`) |
| `feat!:` / `BREAKING CHANGE:` | `feat!: drop Python 3.10 support` | major bump* |
| `docs:` / `chore:` / `ci:` / `test:` / `refactor:` / `perf:` / `build:` / `revert:` | `docs: clarify SLURM template` | no release |

<sub>*While the package is in `0.x` (`allow_zero_version`, `major_on_zero =
false`), a breaking change bumps the **minor** version rather than jumping to
`1.0.0`. Graduating to `1.0.0` is a deliberate decision to make once the API is
stable, since downstream packages pin against these numbers.</sub>

Steps:

1. Create a branch (or fork) and push your change.
2. Open a PR against `main`. The **`tests`** and **`PR title`** checks must
   pass; a malformed title blocks the merge.
3. A maintainer reviews and squash-merges it.

You do **not** need to bump a version or edit a changelog — that is fully
automated once your PR lands.

## How a release happens

The pipeline is fully automated and stores **no secrets**:

1. **`ci.yml`** runs the check suite on every PR (required status checks, so
   `main` is always green).
2. On merge to `main`, **`release.yml`** runs. Its first job uses
   [python-semantic-release](https://python-semantic-release.readthedocs.io/):
   it reads the Conventional Commits since the last release and, *if* there is
   something to release, creates the `vX.Y.Z` git tag and a GitHub Release
   (whose notes are the changelog). It never commits or pushes to `main`, so the
   default `GITHUB_TOKEN` suffices. The version lives only in git tags and is
   read at build time by `hatch-vcs`.
3. The workflow's second job builds the sdist/wheel from that tag and uploads to
   [PyPI](https://pypi.org/project/mreyextract/) via **Trusted Publishing**
   (OIDC — no PyPI token anywhere), gated behind manual approval of the `pypi`
   deployment environment.

Pure `docs:`/`chore:`/`ci:` merges produce no release, so `main` does not spam
PyPI.

## License

By contributing, you agree that your contributions are licensed under the
project's [GPL-3.0](http://www.gnu.org/licenses/gpl-3.0) license.
