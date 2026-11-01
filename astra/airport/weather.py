"""VVTS weather scenarios and a deliberately bounded METAR decoder.

Capacity factors are explicit study assumptions, never inferred aerodrome minima.
Pasted reports are user supplied observations; this module does not fetch live WX.
"""
from datetime import datetime, timezone
import re


PRESETS = {
    'clear': ('Fair weather', '25006KT 9999 FEW020 31/24 Q1010', 1.0, 1.0),
    'rain': ('Rain', '24012KT 6000 RA BKN018 28/25 Q1008', .7, .8),
    'strong_wind': ('Strong wind', '25025G38KT 9999 SCT020 30/24 Q1007', .5, .7),
    'heavy_rain': ('Heavy rain', '24018G28KT 2000 +RA BKN008 OVC015 26/25 Q1006', .4, .6),
    'thunderstorm': ('Thunderstorm', '23020G35KT 1500 +TSRA BKN006CB OVC012 25/24 Q1004', .15, .5),
    'low_visibility': ('Low visibility / ceiling', '25004KT 0600 FG OVC003 24/24 Q1009', .3, .5),
    'severe': ('Severe storm · departures suspended', '23030G45KT 0800 +TSRA BKN003CB OVC008 24/24 Q1002', 0.0, .4),
}


def decode_metar(raw):
    if not isinstance(raw, str) or len(raw) > 500:
        raise ValueError('Enter a VVTS METAR of at most 500 characters.')
    raw = ' '.join(raw.strip().upper().rstrip('=').split())
    tokens = raw.split()
    if tokens and tokens[0] in ('METAR', 'SPECI'):
        tokens.pop(0)
    if len(tokens) < 4 or tokens[0] != 'VVTS':
        raise ValueError('This weather model requires a VVTS METAR.')
    stamp = re.fullmatch(r'(\d{2})(\d{2})(\d{2})Z', tokens[1])
    if not stamp or not (1 <= int(stamp[1]) <= 31 and int(stamp[2]) <= 23 and int(stamp[3]) <= 59):
        raise ValueError('METAR observation time must be DDHHMMZ.')
    # Do not interpret remarks as current weather (e.g. RMK TS MOV E).
    body = tokens[2:tokens.index('RMK') if 'RMK' in tokens else len(tokens)]
    wind = next((re.fullmatch(r'(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)', t)
                 for t in body if re.fullmatch(r'(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)', t)), None)
    if wind is None:
        raise ValueError('A supported METAR wind group (KT or MPS) is required.')
    direction = None if wind[1] == 'VRB' else int(wind[1])
    if direction is not None and direction > 360:
        raise ValueError('Invalid METAR wind direction.')
    multiplier = 1 if wind[4] == 'KT' else 1.943844
    speed = int(wind[2]) * multiplier
    gust = int(wind[3]) * multiplier if wind[3] else None
    if gust is not None and gust < speed:
        raise ValueError('Wind gust cannot be lower than sustained wind.')
    # Metric visibility follows wind and its optional directional-variation group.
    wind_index = body.index(wind[0])
    visibility = next((int(t) for t in body[wind_index + 1:] if re.fullmatch(r'\d{4}', t)), None)
    cavok = 'CAVOK' in body
    if not cavok and visibility is None:
        raise ValueError('Use metric visibility or CAVOK; this decoder does not support SM visibility.')
    clouds = [dict(cover=m[1], height_ft=int(m[2]) * 100, kind=m[3] or '')
              for t in body if (m := re.fullmatch(r'(FEW|SCT|BKN|OVC|VV)(\d{3})(CB|TCU)?', t))]
    ceiling = min((c['height_ft'] for c in clouds if c['cover'] in ('BKN', 'OVC', 'VV')), default=None)
    weather = [t for t in body if re.fullmatch(r'[+-]?(?:VC)?(?:MI|BC|PR|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|SQ|FC|SS|DS)+', t) or t in ('TS', 'VCTS')]
    temp = next((re.fullmatch(r'(M?\d{2})/(M?\d{2})', t) for t in body if re.fullmatch(r'(M?\d{2})/(M?\d{2})', t)), None)
    pressure = next((int(t[1:]) for t in body if re.fullmatch(r'Q\d{4}', t)), None)
    if pressure is None or temp is None or not 850 <= pressure <= 1100:
        raise ValueError('Supported temperature/dewpoint and QNH (Qhhhh) groups are required.')
    number = lambda s: -int(s[1:]) if s.startswith('M') else int(s)
    wx = ' '.join(weather)
    key = ('severe' if ('TS' in wx and max(speed, gust or 0) >= 40) else
           'thunderstorm' if 'TS' in wx else
           'low_visibility' if (visibility is not None and visibility < 1000) or (ceiling is not None and ceiling < 500) else
           'heavy_rain' if '+RA' in wx or (visibility is not None and visibility < 3000) else
           'strong_wind' if max(speed, gust or 0) >= 30 else
           'rain' if 'RA' in wx or 'DZ' in wx else 'clear')
    label, _, factor, taxi = PRESETS[key]
    return dict(raw=raw, station='VVTS', observation_time=tokens[1], wind_direction_deg=direction,
                wind_speed_kt=round(speed, 1), gust_kt=round(gust, 1) if gust else None,
                visibility_m=10000 if cavok else visibility, visibility_at_least=cavok or visibility == 9999,
                weather=weather, clouds=clouds, ceiling_ft=ceiling, temperature_c=number(temp[1]),
                dewpoint_c=number(temp[2]), qnh_hpa=pressure, preset=key, label=label,
                capacity_factor=factor, taxi_factor=taxi)


def preset_weather(key, stamp=None):
    if key not in PRESETS:
        raise ValueError('Unknown weather preset.')
    stamp = stamp or datetime.now(timezone.utc).strftime('%d%H%MZ')
    report = decode_metar(f'METAR VVTS {stamp} {PRESETS[key][1]}')
    report.update(source='SIMULATED', preset=key, label=PRESETS[key][0],
                  capacity_factor=PRESETS[key][2], taxi_factor=PRESETS[key][3])
    return report
