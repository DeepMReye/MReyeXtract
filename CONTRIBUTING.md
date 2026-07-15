# Contributing to MReyeXtract

Thanks for your interest in improving MReyeXtract! It is used across the
OpenMReye ecosystem and depended on by other packages, so we keep the
contribution process lightweight but disciplined. This guide covers how to
submit a change; for how releases are cut, see the
[Development section of the README](README.md#development).

## Getting started

For anything larger than a small fix, please **open an issue first** so we can
agree on the approach before you invest time. Questions are welcome at
zachnudels[at]gmail.com.

## Development setup

MReyeXtract targets **Python 3.11**.

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

1. Create a branch (or fork) and push your change.
2. Open a PR against `main`. CI (`CI` and `Lint PR title`) must pass.
3. A maintainer reviews and **squash-merges** it.

Because PRs are squash-merged, **your PR title becomes the commit message on
`main`**, and that title drives the automatic version bump. It **must** be a
valid [Conventional Commit](https://www.conventionalcommits.org/):

| PR title | Result |
| --- | --- |
| `fix: correct mask resampling origin` | patch release |
| `feat: add --as-pickle output` | minor release |
| `feat!: drop Python 3.10 support` | breaking-change release |
| `docs: clarify SLURM template` | no release |

Other valid types: `perf`, `refactor`, `test`, `build`, `ci`, `chore`,
`revert`. Add `!` after the type (or a `BREAKING CHANGE:` footer) for anything
that breaks backward compatibility. A malformed title will block the merge.

You do **not** need to bump a version or edit a changelog — that is fully
automated once your PR lands.

## License

By contributing, you agree that your contributions are licensed under the
project's [GPL-3.0](http://www.gnu.org/licenses/gpl-3.0) license.
