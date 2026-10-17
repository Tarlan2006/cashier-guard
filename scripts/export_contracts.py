"""Export Pydantic models as portable JSON Schemas for the ML teammates."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.models import Observations, MatchingRequest, RuleCatalog, AnalysisResult, JobResponse  # noqa: E402

for name, model in [("ml1-response", Observations), ("ml2-request", MatchingRequest), ("rules-catalog", RuleCatalog), ("analysis-result", AnalysisResult), ("job-response", JobResponse)]:
    (root / "contracts" / f"{name}.schema.json").write_text(
        json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"Exported {name}.schema.json")

