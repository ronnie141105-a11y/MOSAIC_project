"""Archive public VVTS weather and selected traffic observations for study use.

This captures provider observations, not filed ICAO FPLs or ATC clearances.
Run manually; it does not poll, authenticate, or modify external systems.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.skip_span = 0

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == 'span' and (self.skip_span or 'hide-for-medium-up' in attr.get('class', '').split()):
            self.skip_span += 1
            return
        if tag == 'tr':
            self.row = {'id': attr.get('id', ''), 'cells': [], 'links': []}
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
        elif tag == 'a' and self.row is not None and attr.get('href'):
            self.row['links'].append(attr['href'])

    def handle_data(self, data):
        if self.cell is not None and not self.skip_span:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'span' and self.skip_span:
            self.skip_span -= 1
            return
        if tag in ('td', 'th') and self.row is not None and self.cell is not None:
            self.row['cells'].append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = self.cell = None


def fetch(url, path, cached=False):
    if cached:
        return json.loads(path.read_text(encoding='utf-8'))
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (MOSAIC public aviation study capture)',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read().decode('utf-8')
        headers = dict(response.headers)
    record = {'source_url': url, 'retrieved_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'headers': headers, 'body': body}
    path.write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cached', action='store_true', help='Reparse saved responses without network access')
    parser.add_argument('--callsigns', nargs='*', default=['HVN273', 'VJC147', 'HVN133', 'SIA186', 'MAS766', 'VJC211'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = {
        'metar_6h': 'https://aviationweather.gov/api/data/metar?ids=VVTS&format=json&hours=6',
        'taf': 'https://aviationweather.gov/api/data/taf?ids=VVTS&format=json',
        'flightaware_airport': 'https://www.flightaware.com/live/airport/VVTS',
    }
    records = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, url, args.output / (key + '.json'), args.cached): key for key, url in sources.items()}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                records[key] = future.result()
            except Exception as error:
                print(f'{key}: {error}')
    tables = Tables()
    tables.feed(records['flightaware_airport']['body'])
    traffic = [row for row in tables.rows if row['id'].startswith('Row_')]
    for row in traffic:
        row['flight_url'] = next((link for link in row['links'] if '/live/flight/' in link), None)
        if row['flight_url'] and row['flight_url'].startswith('/'):
            row['flight_url'] = 'https://www.flightaware.com' + row['flight_url']
        row.pop('links')
    board = {'source_url': sources['flightaware_airport'],
             'retrieved_at_utc': records['flightaware_airport']['retrieved_at_utc'],
             'notes': ['Airport-board times retain displayed timezone and status. Estimated times can change.',
                       'En route/scheduled rows do not establish airborne position or holding.',
                       'This is a partial public board, not all airport demand or filed flight plans.'],
             'rows': traffic}
    (args.output / 'traffic_board.json').write_text(json.dumps(board, indent=2), encoding='utf-8')
    flights = {}
    for row in traffic:
        if row['cells'] and row['cells'][0] in args.callsigns and row['flight_url']:
            flights.setdefault(row['cells'][0], row['flight_url'].rstrip('/') + '/tracklog')
    tracks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, url, args.output / (acid + '_tracklog_raw.json'), args.cached): acid for acid, url in flights.items()}
        for future in concurrent.futures.as_completed(futures):
            acid = futures[future]
            try:
                record = future.result()
                parsed = Tables()
                parsed.feed(record['body'])
                samples = []
                # This account's public pages explicitly display EDT (UTC-04:00).
                # Only normalize when that exact timezone is present in the table header.
                edt = any(any('Time (EDT)' in c for c in r['cells']) for r in parsed.rows)
                match = re.search(r'/history/(\d{8})/', record['source_url'])
                day = dt.datetime.strptime(match[1], '%Y%m%d').date() if match else None
                for row in parsed.rows:
                    cells = row['cells']
                    if len(cells) != 9 or not re.fullmatch(r'\d+\.\d+', cells[1]):
                        continue
                    time_utc = None
                    if edt and day:
                        local_time = dt.datetime.strptime(cells[0][4:], '%I:%M:%S %p').time()
                        time_utc = dt.datetime.combine(day, local_time, dt.timezone(dt.timedelta(hours=-4))).astimezone(dt.timezone.utc).isoformat()
                    samples.append({'time_display': cells[0], 'time_utc': time_utc,
                                    'lat': float(cells[1]), 'lon': float(cells[2]),
                                    'course_deg': int(re.search(r'(\d+)°', cells[3])[1]) % 360,
                                    'groundspeed_kt': int(cells[4]),
                                    'altitude_ft': int(cells[6].replace(',', '')),
                                    'reporting_facility': cells[8]})
                result = {'callsign': acid, 'source_url': record['source_url'],
                          'retrieved_at_utc': record['retrieved_at_utc'], 'display_timezone': 'EDT' if edt else 'unverified',
                          'samples': samples, 'filed_flight_plan': None, 'atc_clearance': None}
                (args.output / (acid + '_track.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
                tracks.append({'callsign': acid, 'samples': len(samples), 'last_sample_utc': samples[-1]['time_utc'] if samples else None})
            except Exception as error:
                tracks.append({'callsign': acid, 'error': str(error)})
    print(json.dumps({'traffic_rows': len(traffic), 'tracks': tracks}, indent=2))


if __name__ == '__main__':
    main()
