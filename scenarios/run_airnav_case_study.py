"""Run the recorded arrival and hypothetical spacing cases without AirNav access."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astra.studies.airnav import DEFAULT_DATA, export_study, run_study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out-dir", type=Path, default=Path("output/airnav_case_study"))
    args = parser.parse_args()
    try:
        result = run_study(args.data)
        export_study(result, args.out_dir)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"AirNav study failed: {exc}\n")
    print(json.dumps({case["id"]: case["summary"] for case in result["cases"]}, indent=2))
    print(f"Saved study to {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
