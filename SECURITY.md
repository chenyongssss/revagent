# Security

`revagent` reads local manuscript files and writes local `.revagent` artifacts.

## Boundaries

- Core review planning is local-first and does not upload manuscripts or reviewer comments by default.
- Enabling an OpenAI-compatible provider or external Codex worker can transmit the prompt material selected for that task to the configured provider. Review the provider's data policy before authorizing it.
- The persistent project runtime records task-scoped remote authorization locally; a provider/model/purpose/artifact-class authorization expires automatically and does not authorize unrelated tasks.
- A semantic rubric authorization may transmit a complete project snapshot to the selected provider. It is one-use, expires automatically, and must be created explicitly for the matching review task.
- Protected provider E2E uses only the repository's synthetic benchmark fixture. CI must not upload raw prompts, provider responses, private manuscript data, or review artifacts.
- It does not execute experiments by default.
- `revagent validate --compile` runs the configured LaTeX command locally. Use it only for trusted projects.
- Do not run `revagent` on untrusted LaTeX projects without reviewing included scripts and TeX commands.

## Reporting

For vulnerabilities, open a private security advisory or contact the maintainers
before public disclosure.
