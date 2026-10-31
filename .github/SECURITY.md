# Security policy

## Supported versions

Only the latest released `0.x` version receives security fixes. Until
the first release, fixes land on the `develop` branch.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/miki4iaml/protee/security/advisories/new)
(Security tab → Report a vulnerability).

Include, as far as possible: the affected version or commit, a
description of the issue and its impact, and the steps to reproduce
it.

## What to expect

- Acknowledgement within 7 days. The project is maintained by a single
  person: this is a best-effort target, not a contractual commitment.
- Investigation and, if confirmed, a fix prepared in a private fork of
  the advisory.
- Coordinated disclosure: a GitHub security advisory is published once
  a fix is available, crediting the reporter unless they prefer
  otherwise.

## Scope

- The `protee` package code.
- The hook scripts in `scripts/`.
- The CI workflows in `.github/workflows/`.

Vulnerabilities in third-party dependencies should be reported to
their maintainers; Dependabot alerts are enabled on this repository.
