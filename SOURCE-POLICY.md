# Source and Provenance Policy

Verification is only as good as the evidence used to verify it.

For each consequential external claim, ask:
- Who is the original source?
- Is the source in a position to know?
- Is it current enough for this claim?
- Is it independent, or merely repeating another source?
- Does it describe the exact software/version/environment involved?
- Can the claim be reproduced or checked directly?
- Is there a relevant conflict of interest?

## Default evidence hierarchy for software

1. Direct runtime observation / reproducible experiment
2. Local source code, config, schemas, installed packages
3. Official docs/specification for the exact version
4. Upstream source/release notes/maintainer material
5. Reputable independent technical source with evidence
6. Community discussion
7. AI-generated explanation or model recollection

Items lower on the list can still be useful for discovering hypotheses. They should not silently outrank stronger contradictory evidence.

## Independence

Five pages copying one original statement are one evidentiary lineage, not five confirmations. Prefer independently obtained evidence.

## Time

Store truth with time and conditions when it can change: "verified on DATE against VERSION/ENVIRONMENT", not simply "verified forever".
