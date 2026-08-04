from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rental_workflow_refreshes_tests_preflights_sends_then_persists():
    workflow = (ROOT / ".github" / "workflows" / "rental.yml").read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "python scripts/refresh_rental.py --strict" in workflow
    assert "data/private_rentals.json data/cost_rental.json" in workflow
    steps = [
        workflow.index("python scripts/refresh_rental.py --strict"),
        workflow.index("pytest -q"),
        workflow.index("python scripts/run_rental.py --preflight"),
        workflow.index("python scripts/run_rental.py --send"),
        workflow.index("git add data/private_rentals.json data/cost_rental.json"),
    ]
    assert steps == sorted(steps)
