# Contributing to Loupebox

Bug reports and pull requests are welcome. For anything larger than a small fix, open an issue first so
we can agree on the approach.

## Licensing

* The server, API, admin UI and everything outside `web/widget/` is under the **GNU AGPL-3.0** ([LICENSE](LICENSE)).
* The embeddable widget in `web/widget/` is under the **Apache License 2.0** ([web/widget/LICENSE](web/widget/LICENSE)),
  so sites can embed it without taking on AGPL obligations.

By contributing you agree your change is released under the license of the directory it touches.

## Developer Certificate of Origin (DCO)

Every commit must carry a `Signed-off-by` line certifying that you wrote the change or have the right to
submit it under the project's license ([developercertificate.org](https://developercertificate.org)). Add it with:

```bash
git commit -s -m "fix: describe the change"
```

The line must match your commit author, e.g. `Signed-off-by: Jane Doe <jane@example.com>`. To fix
commits you already made: `git rebase --signoff master` and force-push your branch.

## Development

See the README for setup. Before opening a PR run `pytest`, `ruff check .`, and
`cd web && npm run build && npm test`. Run all three before opening a PR.

## Releasing (maintainers)

1. Set the new version in [VERSION](VERSION) (for example `0.1.0-alpha.2`) and move the `Unreleased` entries in
   [CHANGELOG.md](CHANGELOG.md) under it with the date.
2. Merge that through a PR, then tag the merge commit: `git tag v$(cat VERSION) && git push origin v$(cat VERSION)`.
3. The release workflow checks the tag against `VERSION`, pushes the images to GHCR and creates the GitHub Release
   with the `CHANGELOG.md` section as notes and `docker-compose.yml`, `setup.sh` and `env.example` as downloads.
