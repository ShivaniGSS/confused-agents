"""Validate that every authored fixture loads cleanly and that the
ground-truth provenance map is internally consistent (i.e., the
provenance_label on every datum equals the matching entry in
provenance.json's ground_truth map).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.run_attack import load_attack


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "attacks" / "fixtures"


def _all_attack_dirs() -> list[Path]:
    out: list[Path] = []
    for scenario_dir in sorted(FIXTURE_ROOT.iterdir()):
        if not scenario_dir.is_dir():
            continue
        for adir in sorted(scenario_dir.iterdir()):
            if (adir / "fixture.json").exists():
                out.append(adir)
    return out


@pytest.mark.parametrize("attack_dir", _all_attack_dirs(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_fixture_loads_and_provenance_is_consistent(attack_dir: Path):
    spec = load_attack(attack_dir)

    # Every fixture must declare an invoking principal.
    assert spec.fixture["principals"]["invoking"], attack_dir

    # Walk every datum in fixture.json and check that its provenance_label
    # matches the entry in provenance.json's ground_truth map (and that its
    # 'author' field, when present, agrees with that label).
    ground = spec.provenance["ground_truth"]
    seen: set[str] = set()
    for server_name, snap in spec.fixture["servers"].items():
        for table_name, rows in snap.items():
            for row in rows:
                rid = row.get("id")
                assert rid, f"{attack_dir}: row in {server_name}.{table_name} missing id"
                seen.add(rid)
                lbl = row.get("provenance_label")
                assert lbl, f"{attack_dir}: {rid} missing provenance_label"
                assert rid in ground, (
                    f"{attack_dir}: {rid} not in provenance.json ground_truth"
                )
                assert ground[rid] == lbl, (
                    f"{attack_dir}: provenance_label mismatch for {rid}: "
                    f"row={lbl!r} vs ground_truth={ground[rid]!r}"
                )
                if "author" in row:
                    assert row["author"] == lbl, (
                        f"{attack_dir}: row author != provenance_label for {rid}"
                    )

    # Every provenance ground_truth entry must correspond to an actual datum.
    extras = set(ground) - seen
    assert not extras, f"{attack_dir}: ground_truth references missing data: {sorted(extras)}"


def test_at_least_six_attacks_in_scenario_a():
    """Scenario A end-check: full factorial coverage = 6 attacks."""
    sa = sorted((FIXTURE_ROOT / "scenario_a_calendar").iterdir())
    sa_attacks = [p for p in sa if (p / "fixture.json").exists()]
    assert len(sa_attacks) == 6, [p.name for p in sa_attacks]


def test_18_attacks_total_in_main_corpus():
    """Main corpus is 3 scenarios x 6 attacks = 18 (commit_race is separate)."""
    total = 0
    for s in ("scenario_a_calendar", "scenario_b_docs", "scenario_c_multitenant"):
        d = FIXTURE_ROOT / s
        total += sum(1 for p in d.iterdir() if (p / "fixture.json").exists())
    assert total == 18, total


def test_benign_workload_has_30_items():
    benign = sorted((REPO_ROOT / "attacks" / "benign").iterdir())
    benign_items = [p for p in benign if (p / "fixture.json").exists()]
    assert len(benign_items) == 30, [p.name for p in benign_items]


def test_benign_predicates_are_unsatisfiable():
    benign = sorted((REPO_ROOT / "attacks" / "benign").iterdir())
    for p in benign:
        if not (p / "fixture.json").exists():
            continue
        spec = load_attack(p)
        # Must have an unsatisfiable predicate so attack_success is always False.
        # The harness scoring contract requires {"predicates": {"any": []}} or absent.
        preds = spec.success.get("predicates")
        assert preds == {"any": []} or preds is None, p.name
