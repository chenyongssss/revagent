# Retraction and Citation Graph API Contract Check

Checked: 2026-09-01

`PARALLEL_API_KEY` was not set, so the Parallel Web skill could not execute.
The implementation was checked against official provider documentation instead.

- Crossref Retraction Watch metadata appears in REST API `update-to` entries;
  retractions can be filtered with `update-type:retraction`:
  https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/
- Crossref exposes typed relations and reference relationships, but deposited
  metadata may be incomplete:
  https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/
- OpenAlex work objects expose referenced-work identifiers through its public
  works metadata API. API reference entry point:
  https://help.openalex.org/api-entities/works

RevAgent derives reports only from locally cached responses whose one-use
authorization permits final-report use. Missing metadata is never interpreted
as proof that a work is not retracted or that no citation relationship exists.
