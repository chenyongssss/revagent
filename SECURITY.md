# Security

`revagent` reads local manuscript files and writes local `.revagent` artifacts.

## Boundaries

- It does not upload manuscripts or reviewer comments.
- It does not execute experiments by default.
- `revagent validate --compile` runs the configured LaTeX command locally. Use it only for trusted projects.
- Do not run `revagent` on untrusted LaTeX projects without reviewing included scripts and TeX commands.

## Reporting

For vulnerabilities, open a private security advisory or contact the maintainers
before public disclosure.
