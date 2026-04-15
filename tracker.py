"""
모다올 키워드 포지션 트래커
============================
자동완성 순위 변화를 일별로 추적하고
추이 그래프가 포함된 HTML 리포트를 생성합니다.

사용법:
    python tracker.py record          # 현재 순위 기록 (매시간 호출)
    python tracker.py report          # 전체 추이 리포트 생성
    python tracker.py report --days 7 # 최근 7일 리포트
"""

import requests
import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "tracker_data.json"
KST = timezone(timedelta(hours=9))

BRAND_KEYWORDS = ["모다올", "모다올의원"]
NEGATIVE_TERMS = ["실패", "부작용", "사기", "피해", "소송", "고소", "폐업", "망", "최악", "후회"]
POSITIVE_TERMS = ["후기", "비용", "가격", "생착률", "원장", "비절개", "리뷰", "전후"]


def fetch_google_autocomplete(keyword):
    url = "https://suggestqueries.google.com/complete/search"
    params = {"client": "chrome", "q": keyword + " ", "hl": "ko", "gl": "kr"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[1] if isinstance(data, list) and len(data) > 1 else []
    except Exception:
        return []


def fetch_naver_autocomplete(keyword):
    url = "https://ac.search.naver.com/nx/ac"
    params = {
        "q": keyword, "con": "1", "frm": "nv", "ans": "2",
        "r_format": "json", "r_enc": "UTF-8", "r_unicode": "0",
        "type": "all", "t_koreng": "1", "run": "2",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        suggestions = []
        for item_group in data.get("items", []):
            for item in item_group:
                if isinstance(item, list) and len(item) > 0:
                    suggestions.append(item[0])
                elif isinstance(item, str):
                    suggestions.append(item)
        return suggestions
    except Exception:
        return []


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": []}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def classify_keyword(term, brand_kw):
    """키워드를 긍정/부정/중립으로 분류"""
    suffix = term.replace(brand_kw, "").strip()
    for neg in NEGATIVE_TERMS:
        if neg in suffix:
            return "negative", neg
    for pos in POSITIVE_TERMS:
        if pos in suffix:
            return "positive", pos
    return "neutral", suffix


def record():
    """현재 자동완성 순위를 기록합니다."""
    now = datetime.now(KST)
    data = load_data()

    record_entry = {
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.hour,
        "keywords": {},
    }

    for brand_kw in BRAND_KEYWORDS:
        google = fetch_google_autocomplete(brand_kw)
        naver = fetch_naver_autocomplete(brand_kw)

        kw_data = {"google": [], "naver": []}

        for platform, terms in [("google", google), ("naver", naver)]:
            for rank, term in enumerate(terms, 1):
                sentiment, matched = classify_keyword(term, brand_kw)
                kw_data[platform].append({
                    "rank": rank,
                    "term": term,
                    "sentiment": sentiment,
                    "matched": matched,
                })

        record_entry["keywords"][brand_kw] = kw_data

    data["records"].append(record_entry)
    save_data(data)

    # 요약 출력
    print(f"[{now.strftime('%Y-%m-%d %H:%M KST')}] 순위 기록 완료")
    for brand_kw in BRAND_KEYWORDS:
        for platform in ["google", "naver"]:
            terms = record_entry["keywords"][brand_kw][platform]
            neg_terms = [t for t in terms if t["sentiment"] == "negative"]
            if neg_terms:
                for t in neg_terms:
                    print(f"  [{platform.upper()}] '{t['term']}' #{t['rank']}위")

    return record_entry


def build_daily_summary(data, days=None):
    """기록 데이터를 일별로 집계합니다."""
    records = data["records"]
    if not records:
        return {}

    # 날짜별 그룹핑
    by_date = {}
    for r in records:
        date = r["date"]
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(r)

    # 최근 N일 필터
    if days:
        sorted_dates = sorted(by_date.keys(), reverse=True)[:days]
        by_date = {d: by_date[d] for d in sorted(sorted_dates)}

    # 일별 집계: 각 키워드의 평균 순위, 최고/최저 순위
    daily = {}
    for date, day_records in sorted(by_date.items()):
        daily[date] = {}

        for brand_kw in BRAND_KEYWORDS:
            daily[date][brand_kw] = {}

            for platform in ["google", "naver"]:
                # 해당 날짜의 모든 기록에서 키워드별 순위 수집
                term_ranks = {}
                for r in day_records:
                    terms = r.get("keywords", {}).get(brand_kw, {}).get(platform, [])
                    for t in terms:
                        key = t["term"]
                        if key not in term_ranks:
                            term_ranks[key] = {
                                "ranks": [],
                                "sentiment": t["sentiment"],
                                "matched": t["matched"],
                            }
                        term_ranks[key]["ranks"].append(t["rank"])

                # 평균 순위 계산
                summary = {}
                for term, info in term_ranks.items():
                    ranks = info["ranks"]
                    summary[term] = {
                        "avg_rank": round(sum(ranks) / len(ranks), 1),
                        "best_rank": min(ranks),
                        "worst_rank": max(ranks),
                        "appearances": len(ranks),
                        "sentiment": info["sentiment"],
                        "matched": info["matched"],
                    }

                daily[date][brand_kw][platform] = summary

    return daily


def generate_report(data, days=None):
    """추이 그래프가 포함된 HTML 리포트를 생성합니다."""
    daily = build_daily_summary(data, days)
    if not daily:
        print("기록 데이터가 없습니다. 먼저 'python tracker.py record'를 실행하세요.")
        return None

    dates = sorted(daily.keys())
    now = datetime.now(KST)

    # 키워드별 일별 순위 추출 (그래프용)
    # 부정 키워드와 긍정 키워드 따로 추적
    tracked_negative = {}
    tracked_positive = {}

    for date in dates:
        for brand_kw in BRAND_KEYWORDS:
            platform_data = daily[date].get(brand_kw, {}).get("google", {})
            for term, info in platform_data.items():
                bucket = tracked_negative if info["sentiment"] == "negative" else tracked_positive if info["sentiment"] == "positive" else None
                if bucket is not None:
                    if term not in bucket:
                        bucket[term] = {}
                    bucket[term][date] = info["avg_rank"]

    # 최신 상태 요약
    latest_date = dates[-1]
    latest_negatives = []
    latest_positives = []
    for brand_kw in BRAND_KEYWORDS:
        platform_data = daily[latest_date].get(brand_kw, {}).get("google", {})
        for term, info in platform_data.items():
            entry = {"term": term, "avg_rank": info["avg_rank"], "brand": brand_kw}
            if info["sentiment"] == "negative":
                latest_negatives.append(entry)
            elif info["sentiment"] == "positive":
                latest_positives.append(entry)

    latest_negatives.sort(key=lambda x: x["avg_rank"])
    latest_positives.sort(key=lambda x: x["avg_rank"])

    # Chart.js 데이터 생성
    neg_colors = ["#e74c3c", "#c0392b", "#e67e22", "#d35400", "#f39c12"]
    pos_colors = ["#2ecc71", "#27ae60", "#3498db", "#2980b9", "#1abc9c"]

    def make_datasets(tracked, colors):
        datasets = []
        for i, (term, date_ranks) in enumerate(tracked.items()):
            color = colors[i % len(colors)]
            data_points = []
            for d in dates:
                val = date_ranks.get(d)
                data_points.append(str(val) if val else "null")
            datasets.append({
                "label": term,
                "data": f"[{','.join(data_points)}]",
                "color": color,
            })
        return datasets

    neg_datasets = make_datasets(tracked_negative, neg_colors)
    pos_datasets = make_datasets(tracked_positive, pos_colors)

    dates_js = json.dumps(dates)

    def datasets_js(datasets):
        parts = []
        for ds in datasets:
            parts.append(f"""{{
                label: '{ds["label"]}',
                data: {ds["data"]},
                borderColor: '{ds["color"]}',
                backgroundColor: '{ds["color"]}20',
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6,
                spanGaps: true,
            }}""")
        return ",\n".join(parts)

    # 변화 요약 텍스트
    change_summary = ""
    if len(dates) >= 2:
        first_date = dates[0]
        last_date = dates[-1]
        for term, date_ranks in tracked_negative.items():
            first_rank = date_ranks.get(first_date)
            last_rank = date_ranks.get(last_date)
            if first_rank and last_rank:
                diff = last_rank - first_rank
                if diff > 0:
                    change_summary += f'<div class="change-item good">"{term}" {first_rank}위 → {last_rank}위 (▼{diff} 하락, 개선)</div>\n'
                elif diff < 0:
                    change_summary += f'<div class="change-item bad">"{term}" {first_rank}위 → {last_rank}위 (▲{abs(diff)} 상승, 악화)</div>\n'
                else:
                    change_summary += f'<div class="change-item neutral">"{term}" {last_rank}위 유지</div>\n'

    if not change_summary:
        change_summary = '<div class="change-item neutral">아직 비교할 데이터가 부족합니다. 내일 다시 확인해주세요.</div>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>모다올 키워드 포지션 트래커</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; background: #0f1923; color: #e0e0e0; padding: 30px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ color: #fff; font-size: 24px; margin-bottom: 5px; }}
        .subtitle {{ color: #888; font-size: 14px; margin-bottom: 30px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .stat-card {{ background: #1a2733; border-radius: 12px; padding: 20px; text-align: center; }}
        .stat-num {{ font-size: 36px; font-weight: bold; }}
        .stat-num.red {{ color: #e74c3c; }}
        .stat-num.green {{ color: #2ecc71; }}
        .stat-num.blue {{ color: #3498db; }}
        .stat-num.yellow {{ color: #f1c40f; }}
        .stat-label {{ color: #888; font-size: 13px; margin-top: 5px; }}
        .chart-card {{ background: #1a2733; border-radius: 12px; padding: 25px; margin-bottom: 20px; }}
        .chart-title {{ color: #fff; font-size: 16px; font-weight: bold; margin-bottom: 15px; }}
        .chart-note {{ color: #666; font-size: 12px; margin-top: 8px; }}
        .section-title {{ color: #fff; font-size: 18px; margin: 25px 0 15px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #243447; color: #aaa; padding: 10px 12px; text-align: left; font-size: 12px; text-transform: uppercase; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #243447; font-size: 14px; }}
        tr:hover {{ background: #1e3040; }}
        .rank {{ font-weight: bold; font-size: 16px; }}
        .rank.neg {{ color: #e74c3c; }}
        .rank.pos {{ color: #2ecc71; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
        .badge.negative {{ background: #e74c3c30; color: #e74c3c; }}
        .badge.positive {{ background: #2ecc7130; color: #2ecc71; }}
        .badge.neutral {{ background: #3498db30; color: #3498db; }}
        .change-item {{ padding: 10px 15px; border-radius: 8px; margin-bottom: 8px; font-size: 14px; }}
        .change-item.good {{ background: #2ecc7115; border-left: 3px solid #2ecc71; }}
        .change-item.bad {{ background: #e74c3c15; border-left: 3px solid #e74c3c; }}
        .change-item.neutral {{ background: #3498db15; border-left: 3px solid #3498db; }}
        .footer {{ text-align: center; color: #555; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #243447; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>모다올 키워드 포지션 트래커</h1>
        <p class="subtitle">리포트 생성: {now.strftime('%Y-%m-%d %H:%M KST')} | 추적 기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)</p>

        <div class="grid">
            <div class="stat-card">
                <div class="stat-num red">{len(latest_negatives)}</div>
                <div class="stat-label">부정 키워드</div>
            </div>
            <div class="stat-card">
                <div class="stat-num green">{len(latest_positives)}</div>
                <div class="stat-label">긍정 키워드</div>
            </div>
            <div class="stat-card">
                <div class="stat-num yellow">{latest_negatives[0]['avg_rank'] if latest_negatives else '-'}</div>
                <div class="stat-label">최상위 부정 키워드 순위</div>
            </div>
            <div class="stat-card">
                <div class="stat-num blue">{len(dates)}</div>
                <div class="stat-label">추적 일수</div>
            </div>
        </div>

        <div class="section-title">순위 변화 요약</div>
        <div class="chart-card">
            {change_summary}
        </div>

        <div class="chart-card">
            <div class="chart-title">부정 키워드 순위 추이</div>
            <canvas id="negChart" height="120"></canvas>
            <div class="chart-note">* 숫자가 클수록(아래로) 순위가 낮음 = 좋은 것. 그래프가 위로 가면 악화.</div>
        </div>

        <div class="chart-card">
            <div class="chart-title">긍정 키워드 순위 추이</div>
            <canvas id="posChart" height="120"></canvas>
            <div class="chart-note">* 숫자가 작을수록(위로) 순위가 높음 = 좋은 것. 그래프가 위로 가면 개선.</div>
        </div>

        <div class="section-title">현재 자동완성 상세 ({latest_date})</div>
        <div class="chart-card">
            <table>
                <tr><th>순위</th><th>키워드</th><th>분류</th><th>플랫폼</th></tr>
"""

    for brand_kw in BRAND_KEYWORDS:
        platform_data = daily[latest_date].get(brand_kw, {}).get("google", {})
        sorted_terms = sorted(platform_data.items(), key=lambda x: x[1]["avg_rank"])
        for term, info in sorted_terms:
            rank_class = "neg" if info["sentiment"] == "negative" else "pos" if info["sentiment"] == "positive" else ""
            badge_class = info["sentiment"]
            badge_text = {"negative": "부정", "positive": "긍정", "neutral": "중립"}[info["sentiment"]]
            html += f"""                <tr>
                    <td class="rank {rank_class}">#{info['avg_rank']}</td>
                    <td>{term}</td>
                    <td><span class="badge {badge_class}">{badge_text}</span></td>
                    <td>Google</td>
                </tr>
"""

    html += f"""            </table>
        </div>

        <div class="footer">
            모다올 자동완성 모니터링 시스템 | 자동 생성 리포트
        </div>
    </div>

    <script>
        const dates = {dates_js};

        const chartOptions = {{
            responsive: true,
            interaction: {{ intersect: false, mode: 'index' }},
            scales: {{
                y: {{
                    reverse: true,
                    min: 1,
                    max: 12,
                    ticks: {{ stepSize: 1, color: '#888' }},
                    grid: {{ color: '#243447' }},
                    title: {{ display: true, text: '순위 (1=최상위)', color: '#888' }}
                }},
                x: {{
                    ticks: {{ color: '#888' }},
                    grid: {{ color: '#243447' }}
                }}
            }},
            plugins: {{
                legend: {{ labels: {{ color: '#ccc' }} }},
                tooltip: {{
                    callbacks: {{
                        label: function(ctx) {{
                            return ctx.dataset.label + ': ' + ctx.parsed.y + '위';
                        }}
                    }}
                }}
            }}
        }};

        new Chart(document.getElementById('negChart'), {{
            type: 'line',
            data: {{
                labels: dates,
                datasets: [{datasets_js(neg_datasets)}]
            }},
            options: chartOptions
        }});

        new Chart(document.getElementById('posChart'), {{
            type: 'line',
            data: {{
                labels: dates,
                datasets: [{datasets_js(pos_datasets)}]
            }},
            options: chartOptions
        }});
    </script>
</body>
</html>"""

    report_dir = BASE_DIR / "reports"
    report_dir.mkdir(exist_ok=True)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    report_file = report_dir / f"tracker_{timestamp}.html"

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html)

    # 이메일용 텍스트 리포트도 생성
    text_lines = [
        f"모다올 키워드 포지션 리포트 ({dates[0]} ~ {dates[-1]})",
        "=" * 50,
        "",
    ]

    if latest_negatives:
        text_lines.append("[ 부정 키워드 ]")
        for n in latest_negatives:
            text_lines.append(f"  #{n['avg_rank']}위  {n['term']}")
        text_lines.append("")

    if latest_positives:
        text_lines.append("[ 긍정 키워드 ]")
        for p in latest_positives:
            text_lines.append(f"  #{p['avg_rank']}위  {p['term']}")
        text_lines.append("")

    # 변화 요약 (텍스트)
    if len(dates) >= 2:
        text_lines.append("[ 순위 변화 ]")
        first_date = dates[0]
        last_date = dates[-1]
        for term, date_ranks in tracked_negative.items():
            first_rank = date_ranks.get(first_date)
            last_rank = date_ranks.get(last_date)
            if first_rank and last_rank:
                diff = last_rank - first_rank
                direction = "하락(개선)" if diff > 0 else "상승(악화)" if diff < 0 else "유지"
                text_lines.append(f"  {term}: {first_rank}위 -> {last_rank}위 ({direction})")
        text_lines.append("")

    text_lines += [
        "---",
        f"리포트 생성: {now.strftime('%Y-%m-%d %H:%M KST')}",
        "GitHub: hy28lee/modaol-autocomplete-monitor",
    ]

    email_file = BASE_DIR / "tracker_email.txt"
    with open(email_file, "w", encoding="utf-8") as f:
        f.write("\n".join(text_lines))

    print(f"리포트 생성: {report_file}")
    return report_file


def main():
    parser = argparse.ArgumentParser(description="모다올 키워드 포지션 트래커")
    parser.add_argument("action", choices=["record", "report"], help="실행할 작업")
    parser.add_argument("--days", type=int, help="리포트에 포함할 일수")
    args = parser.parse_args()

    if args.action == "record":
        record()
    elif args.action == "report":
        data = load_data()
        generate_report(data, args.days)


if __name__ == "__main__":
    main()
