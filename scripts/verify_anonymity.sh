#!/bin/bash
# Anonymity verification (CLAUDE.md Section 12).
#
# Greps the repo for known deanonymizing patterns. Run before every
# artifact upload to anonymous.4open.science. One hit is desk
# rejection — exit 1 on any match.

set -e

PATTERNS=(
  "shivani"
  "coltrain"
  "usf"
  "university of san francisco"
  "@example\\.(com|org|edu)"
  "TODO: add name"
  "Author:"
)

HITS=0
# Exclusions:
#   - This script itself (it lists the patterns verbatim).
#   - CLAUDE.md (the internal operating manual; gitignored — must not be
#     uploaded to anonymous.4open.science).
#   - paper_outputs/ (generated tables; not human-edited).
EXCLUDES=(
  --exclude-dir=.git
  --exclude-dir=.venv
  --exclude-dir=.state
  --exclude-dir=results
  --exclude-dir=node_modules
  --exclude-dir=paper_outputs
  --exclude=verify_anonymity.sh
  --exclude=CLAUDE.md
)
for p in "${PATTERNS[@]}"; do
  if grep -ri "${EXCLUDES[@]}" -E "$p" . ; then
    echo "ANONYMITY HIT: $p"
    HITS=$((HITS+1))
  fi
done
if [ "$HITS" -gt 0 ]; then
  echo "FAILED: $HITS anonymity issues."
  exit 1
fi
echo "OK: no anonymity hits."
