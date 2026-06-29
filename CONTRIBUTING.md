# Contributing

`revagent` is an alpha-stage local CLI. Keep changes conservative and focused
on review workflows for computational mathematics manuscripts.

## Development

```powershell
python -m pip install -e .[dev]
python -m pytest
python -m build
```

## Principles

- Prefer minimal, reviewable diffs.
- Do not add behavior that fabricates proof text, verified claims, or experiment results.
- Keep experiment execution opt-in and explicit.
- Preserve local-first operation; avoid network or cloud dependencies in core workflows.
- Add tests for classifier, workspace schema, LaTeX indexing, and CLI behavior when changing those areas.
