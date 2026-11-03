from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sales_workflow_discovers_new_builds_then_tests_preflights_sends_and_persists():
    workflow = (ROOT / ".github" / "workflows" / "sales.yml").read_text(encoding="utf-8")

    assert "contents: write" in workflow
    assert "python scripts/refresh_sales.py --strict" in workflow
    assert "--discovery-limit 8 --max-new 12" in workflow
    assert "--max-private 6 --max-apartment-only 1" in workflow
    assert "--max-new-build-projects 24 --max-new-build-additions 6" in workflow
    assert "--min-new-build-sources 2" in workflow
    assert "data/sales_new_build_candidates.json" in workflow
    positions = [
        workflow.index("python scripts/refresh_sales.py --strict"),
        workflow.index("pytest -q"),
        workflow.index("python scripts/run_sales.py --preflight"),
        workflow.index("python scripts/run_sales.py --send"),
        workflow.index(
            "git add data/sales_listings.json data/sales_insights.json data/sales_new_build_candidates.json"
        ),
    ]
    assert positions == sorted(positions)


def test_scheduled_sales_has_morning_guard_and_one_email_per_day():
    workflow = (ROOT / ".github" / "workflows" / "sales.yml").read_text(encoding="utf-8")

    assert 'cron: "37 0-7 * * *"' in workflow
    assert 'timezone: "Europe/Dublin"' in workflow
    assert "Sync main and check daily morning delivery" in workflow
    assert 'clock" < "0630"' in workflow
    assert 'sent" == "$today"' in workflow
    assert 'if: steps.daily.outputs.skip != \'true\'' in workflow
    assert "data/sales_last_sent_date.txt" in workflow
    assert workflow.index("python scripts/run_sales.py --send") < workflow.index(
        'printf \'%s\\n\' "$today" > data/sales_last_sent_date.txt'
    )
