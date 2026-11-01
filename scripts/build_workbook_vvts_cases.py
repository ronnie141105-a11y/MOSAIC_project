"""Build or reproduce two synthetic connected scenarios from VVTS_scenarios.xlsx."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from astra.studies.workbook_cases import ROOT, build_packages
from astra.studies.vvts_cases import dataset_for_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, default=ROOT/'evidence/VVTS_scenarios.xlsx')
    parser.add_argument('--output', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true', help='Compare saved bytes and parse the runnable tracks')
    args = parser.parse_args()
    for case_id, files in build_packages(args.workbook).items():
        folder = args.output/case_id
        if not args.check:
            folder.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            if args.check:
                if not (folder/name).exists() or (folder/name).read_bytes() != data:
                    raise SystemExit(f'Outdated or missing scenario file: {folder/name}')
            else:
                (folder/name).write_bytes(data)
        dataset = dataset_for_case(folder)
        summary = json.loads(files['summary.json'])
        assert len(dataset.points) == summary['counts']['total']
        print(json.dumps(dict(case_id=case_id, checked=args.check, **summary['counts'],
            violating_pairs=summary['separation_audit']['violating_pairs'],
            sector_peaks={s['id']:s['peak'] for s in summary['sector_occupancy']['sectors']},
            ground_cycle=True,duration_s=summary['duration_s'])), flush=True)


if __name__ == '__main__':
    main()
