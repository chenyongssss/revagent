# Literature Provider API Contract Check

Checked: 2026-09-01

The Parallel Web API was unavailable because `PARALLEL_API_KEY` was not set, so
the contracts below were verified directly against official provider
documentation.

- Crossref REST API: `https://api.crossref.org/works`; bibliographic search and
  work metadata are returned as JSON. Official documentation:
  https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- arXiv API: `https://export.arxiv.org/api/query`; queries use `search_query`,
  paging parameters, and return an Atom feed. Official documentation:
  https://info.arxiv.org/help/api/user-manual.html
- DOI metadata: `https://doi.org/<doi>` with
  `Accept: application/vnd.citationstyles.csl+json`; the resolver may redirect
  to the registration agency metadata service. Official documentation:
  https://citation.doi.org/docs.html

These endpoints retrieve public metadata only. RevAgent must still require a
matching one-use authorization and a passing privacy scan before each network
request.
