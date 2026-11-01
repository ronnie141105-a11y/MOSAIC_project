"""Read-only comparison of the three dated VVTS cases; no simulator mutation."""
import json
from pathlib import Path
from flask import Blueprint, jsonify, render_template, send_file


def build_vvts_case_blueprint(result_dir=None):
    bp = Blueprint('vvts_cases', __name__)
    result_dir = Path(result_dir or Path(__file__).resolve().parents[2]/'output/vvts_three_cases')

    @bp.get('/vvts-cases')
    def page():
        return render_template('vvts_cases.html')

    @bp.get('/api/vvts-cases/results')
    def results():
        path = result_dir/'report.json'
        if not path.exists():
            return jsonify(error='Chưa có báo cáo. Chạy python scripts/run_vvts_cases.py --init trong project.'),404
        try:
            result = json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            return jsonify(error='Không đọc được báo cáo; hãy chạy lại bộ kịch bản.'),503
        return jsonify(result)

    @bp.get('/api/vvts-cases/export/<asset>')
    def export(asset):
        if asset not in ('report.json','report.md','coverage_15min.csv','prediction_errors.csv'):
            return jsonify(error='Không có loại export này.'),404
        path = result_dir/asset
        if not path.exists():
            return jsonify(error='Báo cáo chưa được tạo.'),404
        return send_file(path,as_attachment=True,download_name='vvts_'+asset)

    return bp
