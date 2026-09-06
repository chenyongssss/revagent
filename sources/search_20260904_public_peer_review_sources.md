# Public peer-review sources for silver benchmarking

Retrieved 2026-09-04. This record summarizes an internet search performed after the Parallel Web API was unavailable locally.

## Approved candidates

- OpenReview: public Comments are CC BY 4.0 and metadata is CC0. Only publicly readable records may be used; manuscript licensing must be checked separately. Sources: https://openreview.net/legal/terms and https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc
- F1000Research: published peer-review reports are CC BY; article-level licensing must still be recorded. Source: https://f1000research.com/about/policies
- eLife: reviewed preprints, public reviews, assessments, and author responses are available in maintained JATS XML; verify the item license. Sources: https://elifesciences.org/about/peer-review and https://github.com/elifesciences/elife-article-xml
- PeerJ: use only articles with an open review history and record the page-level license. Example: https://peerj.com/articles/14727/reviews/

## Excluded

- PubPeer prohibits automated scraping, reproduction, and creation of a review database without permission. Source: https://www.pubpeer.com/static/tos
- PeerRead has venue-specific licensing constraints and is not accepted without per-record rights verification. Source: https://github.com/allenai/PeerRead

## Interpretation

Public reviews are licensed evidence written by reviewers, but they are not duplicate annotations against RevAgent's taxonomy. Two isolated subagents can code them into a reproducible silver benchmark. The resulting metrics must be labelled agent-coded public-record proxy metrics, never expert calibration.
