#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}"
ARCHIVE_NAME="confused-agents-artifact"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

ARCHIVE="${OUT_DIR}/${ARCHIVE_NAME}.tar.gz"

echo "==> Packaging artifact from ${REPO_ROOT}"
echo "    Output: ${ARCHIVE}"

echo ""
echo "==> Running anonymity check (source only)..."
ANON_PATTERNS=(
  "sgshukla" "shivani" "coltrain"
  "university of san francisco"
)
ANON_DIRS=(
  "${REPO_ROOT}/capguard"
  "${REPO_ROOT}/defenses"
  "${REPO_ROOT}/mock_mcp"
  "${REPO_ROOT}/scenarios"
  "${REPO_ROOT}/harness"
  "${REPO_ROOT}/orchestrators"
  "${REPO_ROOT}/tests"
  "${REPO_ROOT}/docs/evaluation_reference.md"
  "${REPO_ROOT}/docs/repo_reference.md"
  "${REPO_ROOT}/ARTIFACT_README.md"
  "${REPO_ROOT}/README.md"
  "${REPO_ROOT}/pyproject.toml"
  "${REPO_ROOT}/scripts/compute_paper_tables.py"
  "${REPO_ROOT}/scripts/audit_traces.py"
  "${REPO_ROOT}/scripts/corpus_audit.py"
)
ANON_FAIL=0
for pat in "${ANON_PATTERNS[@]}"; do
  hits=$(grep -rl --include="*.py" --include="*.md" --include="*.json" \
    --include="*.sh" --include="*.toml" \
    --exclude-dir="__pycache__" \
    -i "$pat" "${ANON_DIRS[@]}" 2>/dev/null || true)
  if [[ -n "$hits" ]]; then
    echo "  ANONYMITY HIT ($pat):"
    echo "$hits" | head -5
    ANON_FAIL=1
  fi
done
if [[ "$ANON_FAIL" -eq 1 ]]; then
  echo "FAILED: anonymity check — fix the above before uploading."
  exit 1
fi
echo "  OK: no anonymity hits in included source files."

echo ""
echo "==> Building file list..."

SOURCE_INCLUDES=(
  "ARTIFACT_README.md"
  "README.md"
  "LICENSE"
  "pyproject.toml"
  "requirements.txt"
  "capguard/"
  "defenses/"
  "mock_mcp/"
  "scenarios/"
  "harness/"
  "orchestrators/"
  "tests/"
  "scripts/compute_paper_tables.py"
  "scripts/audit_traces.py"
  "scripts/corpus_audit.py"
  "scripts/verify_anonymity.sh"
  "scenarios/CORPUS_CONTRACT.md"
  "docs/evaluation_reference.md"
  "docs/repo_reference.md"
)

ARCHIVE_A="${OUT_DIR}/${ARCHIVE_NAME}-source.tar.gz"
ARCHIVE_B="${OUT_DIR}/${ARCHIVE_NAME}-traces.tar.gz"

echo ""
echo "==> Package A: source + aggregate results"
echo "    ${ARCHIVE_A}"

TMP_LIST=$(mktemp)
trap "rm -f ${TMP_LIST}" EXIT

cd "${REPO_ROOT}"

for item in "${SOURCE_INCLUDES[@]}"; do
  if [[ -e "$item" ]]; then
    echo "$item" >> "${TMP_LIST}"
  else
    echo "  [WARN] missing: $item"
  fi
done

TRACE_DIRS=(
  "results/sweep3_gpt41_ijkl_k10"
  "results/sweep3_llama_ijkl_k10"
  "results/ah_claude_k10"
  "results/ah_llama_k10"
  "results/production_campaign/gpt41_k10_20260429-162857"
)
for d in "${TRACE_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    for f in "$d/summary.jsonl" "$d/RUN_REPORT.md" "$d/defense_landscape_matrix.json" \
              "$d/coverage_complementarity.json" "$d/evaluation_manifest.json" \
              "$d/degradation_curves.json"; do
      [[ -f "$f" ]] && echo "$f" >> "${TMP_LIST}"
    done
    for subf in "$d"/observability/*/summary.jsonl "$d"/observability/*/RUN_REPORT.md \
                "$d"/observability/*/defense_landscape_matrix.json; do
      [[ -f "$subf" ]] && echo "$subf" >> "${TMP_LIST}"
    done
  else
    echo "  [WARN] missing trace dir: $d"
  fi
done

tar --exclude="*/__pycache__/*" --exclude="*/.git/*" --exclude="*/*.egg-info/*" \
    --exclude="*/.venv/*" --exclude="*/llm_cache/*" --exclude="*/run_meta.txt" \
    --exclude="*/.env" --exclude="*/CLAUDE.md" \
    -czf "${ARCHIVE_A}" --files-from="${TMP_LIST}" 2>/dev/null

SIZE_A=$(du -sh "${ARCHIVE_A}" | cut -f1)
TOTAL_A=$(tar -tzf "${ARCHIVE_A}" | wc -l | tr -d ' ')
echo "    Created: ${SIZE_A} (${TOTAL_A} files)"

echo ""
echo "==> Package B: full per-run traces (element 4 — for §7.3 audit)"
echo "    ${ARCHIVE_B}"
echo "    (This may take 1-2 minutes due to trace volume)"

tar --exclude="*/__pycache__/*" --exclude="*/.git/*" --exclude="*/*.egg-info/*" \
    --exclude="*/.venv/*" --exclude="*/llm_cache/*" --exclude="*/run_meta.txt" \
    --exclude="*/.env" --exclude="*/CLAUDE.md" \
    -czf "${ARCHIVE_B}" \
    results/sweep3_gpt41_ijkl_k10/ \
    results/sweep3_llama_ijkl_k10/ \
    results/ah_claude_k10/ \
    results/ah_llama_k10/ \
    2>/dev/null

SIZE_B=$(du -sh "${ARCHIVE_B}" | cut -f1)
TOTAL_B=$(tar -tzf "${ARCHIVE_B}" | wc -l | tr -d ' ')
echo "    Created: ${SIZE_B} (${TOTAL_B} files)"

echo ""
echo "==> Summary"
echo "    Package A (source + summaries): ${ARCHIVE_A}  [${SIZE_A}]"
echo "    Package B (full traces):         ${ARCHIVE_B}  [${SIZE_B}]"
echo ""
echo "==> Upload instructions for anonymous.4open.science:"
echo "    1. Create a new anonymous repository"
echo "    2. Upload Package A as the primary artifact"
echo "    3. Upload Package B as a supplementary data release"
echo "       (or host on Zenodo / OSF with anonymous link)"
echo "    4. Set expiration date to cover the full review period"
echo "    5. Copy both links into the paper's artifact appendix (§8)"
echo ""
echo "==> Quick verification (run on reviewer's machine):"
echo "    tar -tzf confused-agents-artifact-source.tar.gz | head -20"
echo "    python scripts/compute_paper_tables.py --axis-rollup"
echo "    python scripts/audit_traces.py --cited-only"
