"""Build the two active study cases from reviewed AirNav screen labels.

Video labels establish identities and visibility times, not ADS-B coordinates,
filed flight plans or actual runway events. Tracks are synthetic procedure paths.
No optimizer or weather/ATFM experiment is executed here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_synthetic_vvts_cases import (
    ARRIVAL_PROCEDURES, DEPARTURE_PROCEDURES, CAPACITY, STEP_S,
    FLIGHT_FIELDS, FPL_FIELDS, TRACK_FIELDS, FLOW_FIELDS,
    assign_slots, resequence_synthetic_arrivals, template, make_positions,
    generated_flights, iso, parse_stamp, json_bytes, csv_bytes, conflict_audit,
)

OUT = ROOT / 'scenarios/reconstructed/vvts_video_cases'
CASES = (
    dict(id='nominal', label='Thông thường · 08/10/2026',
         local_start='2026-10-08T09:00:00+07:00', local_end='2026-10-08T11:00:00+07:00'),
    dict(id='holiday_peak', label='Cao điểm Tết · 22/02/2026',
         local_start='2026-02-22T10:00:00+07:00', local_end='2026-02-22T12:00:00+07:00'),
)
# Airport identifiers are metadata only; the assigned terminal sector and
# STAR/SID below are explicit model assumptions, not recovered filed routes.
ICAO = dict(HAN='VVNB', DAD='VVDN', HPH='VVHP', HUI='VVPB', THD='VVTX',
    VCL='VVCA', VII='VVVH', VDH='VVDH', PQC='VVPQ', VCS='VVCS', CXR='VVCR',
    DLI='VVDL', TBB='VVTH', UIH='VVPC', RMQ='RCMQ', TPE='RCTP', HKG='VHHH',
    ICN='RKSI', PUS='RKPK', PVG='ZSPD', CAN='ZGGG', KUL='WMKK', DMK='VTBD',
    BKK='VTBS', SIN='WSSS', DPS='WADD', CGK='WIII', MEL='YMML',
    NRT='RJAA', MNL='RPLL', LHR='EGLL', SGN='VVTS')
NORTH_IATA = {'HAN','HPH','HUI','THD','VII','VDH','CAN','TPE','RMQ','HKG','ICN','PUS','PVG','NRT','LHR'}
SW_IATA = {'PQC','VCS','KUL','DMK','BKK','SIN','DPS','CGK','MEL'}


def estimate_event(flight, start, end):
    """Estimate a runway target from screen visibility, with explicit uncertainty."""
    arrivals = flight['direction'] == 'arrival'
    numeric = [o for o in flight['observations']
               if o['altitude_ft'] is not None and not o['ambiguous']]
    if numeric:
        sample = min(numeric, key=lambda o: (o['altitude_ft'], o['utc']))
        altitude = max(0, sample['altitude_ft'] - 33)
        # This is only a timing proxy. It does not assert a 2,000 fpm final.
        seconds = min(900, altitude * 60 / 2000)
        moment = parse_stamp(sample['utc']) + timedelta(seconds=seconds if arrivals else -seconds)
        method = 'minimum_visible_altitude_plus_descent_proxy' if arrivals else 'minimum_visible_altitude_minus_climb_proxy'
    else:
        moment = parse_stamp(flight['last_seen_utc'] if arrivals else flight['first_seen_utc'])
        if arrivals:
            moment += timedelta(minutes=4)
        method = 'last_visibility_plus_4min' if arrivals else 'first_visibility'
    lower = start if arrivals else start-timedelta(minutes=15)
    clipped = min(max(moment, lower), end - timedelta(seconds=1))
    return clipped, dict(method=method, unclipped_target_utc=iso(moment),
                         clipped_to_reconstruction_bounds=clipped != moment,
                         actual_event_verified=False)


def input_flights(case, evidence):
    start, end = parse_stamp(case['local_start']), parse_stamp(case['local_end'])
    result = []
    for observed in evidence['flights']:
        if observed['case_id'] != case['id']:
            continue
        route = observed['route_iata']
        if route and ((observed['direction']=='arrival' and route[1]!='SGN') or
                      (observed['direction']=='departure' and route[0]!='SGN')):
            raise ValueError('Screen route contradicts recording direction')
        other = (route[0] if observed['direction']=='arrival' else route[1]) if route else None
        planned, timing = estimate_event(observed, start, end)
        result.append(dict(callsign=observed['display_callsign'], direction=observed['direction'],
            aircraft_type=observed['aircraft_type'] or 'A320',
            other_airport=ICAO.get(other, other or 'UNKNOWN'), other_iata=other,
            aircraft_type_assumed=not bool(observed['aircraft_type']),
            planned=planned, evidence='video_label_identity_with_synthetic_path',
            source_file=observed['source_file'], timing=timing,
            first_seen_utc=observed['first_seen_utc'], last_seen_utc=observed['last_seen_utc']))
    if case['id']=='nominal':
        # The supplied nominal arrival MP4 is a byte-identical copy of the
        # February departures. Keep the prior 23-arrival assumption visible.
        for flight in generated_flights('nominal', start, end):
            if flight['direction']!='arrival':
                continue
            result.append({**flight, 'other_iata':None, 'aircraft_type_assumed':True,
                'evidence':'synthetic_missing_oct8_arrival_recording', 'source_file':None,
                'timing':dict(method='deterministic_synthetic_schedule', actual_event_verified=False),
                'first_seen_utc':None, 'last_seen_utc':None})
    result.sort(key=lambda f:(f['planned'],f['callsign']))
    if len({f['callsign'] for f in result}) != len(result):
        raise ValueError('A case needs unique aircraft identities')
    for index, flight in enumerate(result):
        group = 'north' if flight['other_iata'] in NORTH_IATA else 'southwest' if flight['other_iata'] in SW_IATA else 'east'
        if not flight['other_iata']:
            from scripts.build_synthetic_vvts_cases import sector
            group = sector(flight['other_airport'])
        choices = ARRIVAL_PROCEDURES[group] if flight['direction']=='arrival' else DEPARTURE_PROCEDURES[group]
        flight['_index'], flight['_procedure'] = index, choices[index % len(choices)]
    scheduled = []
    for flight in result:
        flight['initially_airborne'] = flight['direction']=='departure' and flight['planned']<start
        if flight['initially_airborne']:
            flight['simulated_slot']=flight['planned']
        else:
            scheduled.append(flight)
    assign_slots(scheduled, start, CAPACITY[case['id']], case['id'], set())
    resequence_synthetic_arrivals(scheduled, set(), start, CAPACITY[case['id']], case['id'])
    return result


def build_case(case, evidence):
    case_id = case['id']
    start, end = parse_stamp(case['local_start']), parse_stamp(case['local_end'])
    flights = input_flights(case, evidence)
    tracks, flight_rows, fpl_rows, metadata, positions_by_cs = [], [], [], [], {}
    for flight in flights:
        cs, direction = flight['callsign'], flight['direction']
        arrival = direction=='arrival'
        adep, ades = (flight['other_airport'],'VVTS') if arrival else ('VVTS',flight['other_airport'])
        flight_id = f'{case_id}:{cs}'
        proc = flight['_procedure']
        relative, fixes, release = template(proc, flight['_index'] if arrival else 0)
        positions = make_positions(flight, relative, start, end)
        positions_by_cs[cs] = positions
        runway = '25R' if arrival else '25L'
        for point in positions:
            tracks.append(dict(flight_id=flight_id,callsign=cs,aircraft_type=flight['aircraft_type'],
                adep=adep,ades=ades,time_utc=point['timestamp'],lat=point['latitude'],lon=point['longitude'],
                altitude_ft=point['altitude'],ground_speed_kt=point['groundSpeed'],
                heading_deg=point['heading'],vertical_speed_fpm=point['verticalRate'],
                on_ground=str(point['onGround']).lower(),source='synthetic_procedure_video_population'))
        planned_dep = flight['planned']-timedelta(minutes=95) if arrival else flight['planned']
        planned_arr = flight['planned'] if arrival else flight['planned']+timedelta(minutes=90)
        flight_rows.append(dict(flight_id=flight_id,callsign=cs,aircraft_type=flight['aircraft_type'],
            adep=adep,ades=ades,status='reconstructed_scenario',
            scheduled_departure_utc=iso(planned_dep),scheduled_arrival_utc=iso(planned_arr),
            actual_takeoff_utc='',actual_landing_utc='',actual_offblock_utc='',actual_inblock_utc='',
            runway=runway,source=flight['evidence']))
        fpl_rows.append(dict(flight_id=flight_id,callsign=cs,aircraft_type=flight['aircraft_type'],
            adep=adep,ades=ades,eobt_utc=iso(planned_dep-timedelta(minutes=15)),
            eet_min=95 if arrival else 90,filed_route=proc,issued_at_utc='',raw_fpl='',
            source='synthetic_route_assumption_not_observed_fpl'))
        metadata.append(dict(flight_id=flight_id,callsign=cs,aircraft_type=flight['aircraft_type'],
            aircraft_type_assumed=flight['aircraft_type_assumed'],direction=direction,adep=adep,ades=ades,
            procedure=proc,runway=runway,route_fixes=fixes,direct_from_fix=release,
            direct_to_fix=('BOMSU' if proc.endswith('J') else 'SOKAN') if arrival else '',
            evidence=flight['evidence'],source_file=flight['source_file'],
            first_seen_utc=flight['first_seen_utc'],last_seen_utc=flight['last_seen_utc'],
            initially_airborne=flight['initially_airborne'],
            timing=flight['timing'],planned_event_utc=iso(flight['planned']),
            simulated_slot_utc=iso(flight['simulated_slot']),
            simulated_delay_min=round((flight['simulated_slot']-flight['planned']).total_seconds()/60,1),
            first_track_utc=positions[0]['timestamp'],last_track_utc=positions[-1]['timestamp'],
            positions_basis='synthetic_STAR_SID_not_extracted_ADSB',
            actual_landing_verified=False,actual_takeoff_verified=False))
    counts = Counter(f['direction'] for f in flights)
    observed = sum(f['source_file'] is not None for f in flights)
    counts = dict(total=len(flights),arrivals=counts['arrival'],departures=counts['departure'],
                  video_identities=observed,synthetic_identities=len(flights)-observed,
                  departures_already_airborne=sum(f['initially_airborne'] for f in flights))
    coverage = dict(recordings=[s for s in evidence['sources'] if s['case_id']==case_id],
        complete_airport_traffic=False,exact_positions_available=False,
        missing_arrival_recording=case_id=='nominal')
    limitations = [
        'Nhãn video xác nhận các chuyến nhìn thấy; danh sách này chưa phải toàn bộ lưu lượng sân bay.',
        'Tuyến STAR/SID, vị trí, thời gian cất/hạ cánh và khoảng cách giãn cách là mô phỏng; không phải FPL hoặc huấn lệnh ATC đã xác nhận.',
        'Dùng cấu hình nghiên cứu hiện có: tàu bay đến 25R, tàu bay đi 25L. Không mô phỏng taxi hoặc thời tiết.',
        'Tổng chuyến nhìn thấy gồm cả chuyến đi đã ở trên không khi bắt đầu; chúng không được tính là cất cánh mới trong khung nghiên cứu.',
        'Giữ giãn cách đến 10 NM / cùng hướng 20 NM trong vùng kiểm tra TMA; một số chuyến phải chạy tiếp sau khung hai giờ.',
    ]
    if case_id=='nominal':
        limitations.insert(0,'Thiếu video tàu bay đến ngày 08/10: file ARR_OCT82026 trùng video tàu bay đi ngày 22/02. 23 chuyến đến được giữ là giả định tổng hợp.')
    manifest = dict(schema_version=1,case_id=case_id,label=case['label'],
        local_start=case['local_start'],local_end=case['local_end'],counts=counts,coverage=coverage,
        basis=f"{counts['arrivals']} chuyến đến + {counts['departures']} chuyến đi có nhãn trong video; đường bay mô phỏng." if case_id=='holiday_peak' else
              f"{counts['departures']} chuyến đi có nhãn trong video + 23 chuyến đến giả định; ca tạm thời.",
        limitations=limitations,scenario_kind='video_population_synthetic_procedure_reconstruction',
        generated_by='scripts/build_video_vvts_cases.py',sample_step_s=STEP_S,
        capacity_basis='Existing study assumption: 44/hour nominal, 46/hour holiday, combined movements; not measured from video.',
        geometry='Existing 25R arrival / 25L departure procedure model',
        baseline_sequencing='Deterministic route separation; no GA or ATFM optimization',flights=metadata)
    demand=[]
    for quarter in range(8):
        left=start+timedelta(minutes=15*quarter);right=left+timedelta(minutes=15)
        demand.append(dict(start_utc=iso(left),end_utc=iso(right),resource='VVTS_RUNWAY_TOTAL',
            flights_per_interval=sum(left<=f['planned']<right for f in flights),
            evidence='estimated_scenario_demand_not_observed_movements',source='video_visibility_timing_proxy'))
    summary=dict(counts=counts,window_start_utc=iso(start),window_end_utc=iso(end),
        replay_end_utc=max(m['last_track_utc'] for m in metadata),
        flights_resequenced_after_window=sum(f['simulated_slot']>=end for f in flights),
        separation_audit=conflict_audit(positions_by_cs,start,end,{f['callsign']:f['direction'] for f in flights}))
    return {'manifest.json':json_bytes(manifest),'summary.json':json_bytes(summary),
        'tracks.csv':csv_bytes(TRACK_FIELDS,tracks),'flights.csv':csv_bytes(FLIGHT_FIELDS,flight_rows),
        'fpl.csv':csv_bytes(FPL_FIELDS,fpl_rows),'demand.csv':csv_bytes(FLOW_FIELDS,demand)}


README = """# Hai kịch bản VVTS từ video AirNav

Chỉ giữ **08/10/2026 09:00–11:00 ICT** và **22/02/2026 10:00–12:00 ICT**.
Ca ngày 07/10 đã được loại khỏi bộ ca đang chạy theo yêu cầu của người dùng.

## Chạy trong MOSAIC

Từ thư mục dự án, chạy:

```powershell
.\\.venv\\Scripts\\python.exe main.py --mock --profile tsn_tma
```

Mở `http://127.0.0.1:8050/case-scenarios`, chọn **Nạp vào radar TMA**,
sau đó **Phát**. Mở radar TMA để xem trên màn hình tiếp cận hiện có.
Có tạm dừng, tốc độ 1–60 lần, về đầu và thanh chọn thời điểm. Tải ca khác
hoặc bấm Kết thúc sẽ xóa lưu lượng của ca trước. Không cần BlueSky/video/OCR
để chạy; các dữ liệu nhỏ trong thư mục này đủ cho mô phỏng.

## Nguồn và giới hạn

- Video tháng 2 cung cấp nhãn cho cả chuyến đến và đi.
- Video ngày 08/10 chỉ cung cấp chuyến đi. `VVTS_ARR_OCT82026.mp4` có cùng
  SHA256 với `VVTS_DEP_FEB22_2026.mp4`, và đồng hồ trong video là 22/02.
  23 chuyến đến tháng 10 dùng lại giả định tổng hợp của ca trước; có mã MOSN.
- `evidence/video_observations.json` giữ nhãn gốc, đồng hồ UTC, thời điểm
  trong video, vùng ảnh và các trường đọc được. Mỗi nhãn máy đọc được phải
  xuất hiện ít nhất hai lần. Các mũi tên bị đọc thành chữ số 1 đã được đối
  chiếu và gộp, không tạo chuyến bay trùng. Đây là tập chuyến **nhìn thấy**,
  chưa khẳng định đã thu thập đủ mọi chuyển động sân bay.
- Tọa độ trên radar là đường bay **mô phỏng** theo STAR/SID 25R/25L hiện có,
  không phải dữ liệu ADS-B trích xuất từ video. FPL, thời điểm runway và
  direct-to là giả định. Các cột actual trong flights.csv luôn để trống.
- Thời điểm mục tiêu ước lượng từ lần nhìn thấy và độ cao thấp nhất, sau đó
  xếp lại theo đường bay và giãn cách 10/20 NM. Độ cao/GS trong nhãn được
  giữ làm bằng chứng; không sao chép nhãn chồng lấn hay GS thấp bất thường
  thành quỹ đạo. Áp dụng tốc độ và giới hạn 2.000 ft/min của mô hình hiện có.
- Khung nghiên cứu dài hai giờ; các chuyến còn trong hàng đợi có phần đuôi
  chạy tiếp sau hai giờ. Đây không phải bản phát lại chính xác lịch sử.
- Các chuyến đi đã lên cao khi video bắt đầu có đoạn bay mô phỏng trước
  đầu khung, không được đưa trở lại đường cất cánh. Tổng chuyến nhìn thấy
  không đồng nghĩa tổng lượt cất/hạ cánh trong hai giờ.
- Không chạy GA, tính hiệu quả ATFM hay thêm METAR/thời tiết ở bước này.

`manifest.json` ghi nguồn và giả định cho từng chuyến. `tracks.csv` là dữ
liệu chạy radar; `flights.csv`, `fpl.csv`, `demand.csv` là đầu vào mô phỏng.
`summary.json` chỉ kiểm tra dữ liệu/giãn cách, không phải báo cáo nghiên cứu.
Các bộ dữ liệu cũ ở recorded/synthetic là lưu trữ của lần xây dựng trước.

## Tạo lại dữ liệu

```powershell
.\\.venv\\Scripts\\python.exe scripts/build_video_vvts_cases.py
```

Bộ tạo mặc định đọc bằng chứng đã đóng gói. Dùng `--evidence-dir` để nhập
bản nhãn đã đối chiếu khác, `--output` để tạo bản thử và `--check` để kiểm
tra khả năng tạo lại đúng từng byte. Không cần thư viện xử lý video.
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,default=OUT/'evidence')
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    evidence=json.loads((args.evidence_dir/'video_observations.json').read_text(encoding='utf-8'))
    if any(f['case_id'] not in {'nominal','holiday_peak'} for f in evidence['flights']):
        raise ValueError('October 7 was removed; supply only the two active cases')
    files={'README.md':README.encode('utf-8'),
        'study.json':json_bytes(dict(schema_version=1,cases=list(CASES),excluded_case='2026-10-07',
                                    basis='user recordings with synthetic procedure paths')),
        'evidence/video_observations.json':json_bytes(evidence)}
    inventory=json.loads((args.evidence_dir/'archive_inventory.json').read_text(encoding='utf-8'))
    files['evidence/archive_inventory.json']=json_bytes([item for item in inventory if 'OCT7' not in item['file']])
    for case in CASES:
        outputs=build_case(case,evidence)
        files.update({case['id']+'/'+name:data for name,data in outputs.items()})
        print(case['id'],json.loads(outputs['manifest.json'])['counts'],flush=True)
    changed=[]
    for relative,data in files.items():
        path=args.output/relative
        if args.check:
            if not path.exists() or path.read_bytes()!=data: changed.append(relative)
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    if changed:
        raise SystemExit('Rebuild differs: '+', '.join(changed))
    print('Verified' if args.check else 'Built',args.output)


if __name__=='__main__':
    main()
