"""
모다올 자동완성 키워드 모니터링 도구
=====================================
네이버/구글 자동완성에서 브랜드 키워드를 모니터링하고
부정 키워드가 감지되면 알림을 보냅니다.

사용법:
    python monitor.py              # 1회 체크
    python monitor.py --watch      # 주기적 반복 체크
    python monitor.py --report     # HTML 리포트 생성
"""

import requests
import json
import os
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

# Windows 콘솔 UTF-8 출력 설정
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────
# 자동완성 수집
# ──────────────────────────────────────────────

def fetch_naver_autocomplete(keyword):
    """네이버 자동완성 키워드를 가져옵니다."""
    url = "https://ac.search.naver.com/nx/ac"
    params = {
        "q": keyword,
        "con": "1",
        "frm": "nv",
        "ans": "2",
        "r_format": "json",
        "r_enc": "UTF-8",
        "r_unicode": "0",
        "type": "all",
        "t_koreng": "1",
        "run": "2",
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
    except Exception as e:
        print(f"  [오류] 네이버 자동완성 조회 실패 ({keyword}): {e}")
        return []


def fetch_google_autocomplete(keyword):
    """구글 자동완성 키워드를 가져옵니다."""
    url = "https://suggestqueries.google.com/complete/search"
    params = {
        "client": "firefox",
        "q": keyword,
        "hl": "ko",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 1:
            return data[1]
        return []
    except Exception as e:
        print(f"  [오류] 구글 자동완성 조회 실패 ({keyword}): {e}")
        return []


def fetch_all_suggestions(brand_keywords):
    """모든 브랜드 키워드에 대해 네이버/구글 자동완성을 수집합니다."""
    results = {}
    for kw in brand_keywords:
        results[kw] = {
            "naver": fetch_naver_autocomplete(kw),
            "google": fetch_google_autocomplete(kw),
        }
    return results


# ──────────────────────────────────────────────
# 부정 키워드 감지
# ──────────────────────────────────────────────

def detect_negatives(suggestions, negative_terms):
    """자동완성 결과에서 부정 키워드를 찾아냅니다."""
    alerts = []
    for brand_kw, platforms in suggestions.items():
        for platform, terms in platforms.items():
            for rank, term in enumerate(terms, 1):
                for neg in negative_terms:
                    if neg in term:
                        alerts.append({
                            "brand_keyword": brand_kw,
                            "platform": platform,
                            "rank": rank,
                            "suggestion": term,
                            "matched_negative": neg,
                        })
    return alerts


# ──────────────────────────────────────────────
# 로그 저장 및 변화 추적
# ──────────────────────────────────────────────

def save_log(suggestions, alerts, log_dir):
    """체크 결과를 JSON 로그로 저장합니다."""
    log_dir = BASE_DIR / log_dir
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "suggestions": suggestions,
        "alerts": alerts,
    }

    log_file = log_dir / f"check_{timestamp}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    # 최신 상태를 latest.json에도 저장 (변화 비교용)
    latest_file = log_dir / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    return log_file


def detect_changes(suggestions, log_dir):
    """이전 체크 결과와 비교하여 변화를 감지합니다."""
    latest_file = BASE_DIR / log_dir / "latest.json"
    if not latest_file.exists():
        return None

    with open(latest_file, "r", encoding="utf-8") as f:
        prev = json.load(f)

    changes = []
    prev_suggestions = prev.get("suggestions", {})

    for brand_kw, platforms in suggestions.items():
        for platform, terms in platforms.items():
            prev_terms = prev_suggestions.get(brand_kw, {}).get(platform, [])
            new_terms = [t for t in terms if t not in prev_terms]
            removed_terms = [t for t in prev_terms if t not in terms]

            if new_terms:
                changes.append({
                    "type": "new",
                    "brand_keyword": brand_kw,
                    "platform": platform,
                    "terms": new_terms,
                })
            if removed_terms:
                changes.append({
                    "type": "removed",
                    "brand_keyword": brand_kw,
                    "platform": platform,
                    "terms": removed_terms,
                })

    return changes


# ──────────────────────────────────────────────
# 알림
# ──────────────────────────────────────────────

def send_console_alert(alerts, changes):
    """콘솔에 경고 메시지를 출력합니다."""
    if alerts:
        print("\n" + "=" * 60)
        print("🚨 부정 키워드 감지!")
        print("=" * 60)
        for a in alerts:
            print(f"  [{a['platform'].upper()}] '{a['suggestion']}' "
                  f"(#{a['rank']}위) — 매칭: '{a['matched_negative']}'")
        print("=" * 60)
    else:
        print("\n✅ 부정 키워드가 감지되지 않았습니다.")

    if changes:
        print("\n📊 이전 체크 대비 변화:")
        for c in changes:
            icon = "🆕" if c["type"] == "new" else "❌"
            label = "새로 등장" if c["type"] == "new" else "사라짐"
            print(f"  {icon} [{c['platform'].upper()}] {label}: {', '.join(c['terms'])}")


def send_telegram_alert(alerts, config):
    """텔레그램으로 알림을 보냅니다."""
    tg = config["alert"]["telegram"]
    if not tg["enabled"] or not alerts:
        return

    lines = ["🚨 모다올 자동완성 부정 키워드 감지!\n"]
    for a in alerts:
        lines.append(
            f"• [{a['platform'].upper()}] \"{a['suggestion']}\" "
            f"(#{a['rank']}위)"
        )
    lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    message = "\n".join(lines)

    url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
    try:
        requests.post(url, json={"chat_id": tg["chat_id"], "text": message}, timeout=10)
        print("  📨 텔레그램 알림 전송 완료")
    except Exception as e:
        print(f"  [오류] 텔레그램 전송 실패: {e}")


def send_email_alert(alerts, config):
    """이메일로 알림을 보냅니다."""
    email_cfg = config["alert"]["email"]
    if not email_cfg["enabled"] or not alerts:
        return

    import smtplib
    from email.mime.text import MIMEText

    lines = ["모다올 자동완성 부정 키워드가 감지되었습니다.\n"]
    for a in alerts:
        lines.append(
            f"- [{a['platform'].upper()}] \"{a['suggestion']}\" "
            f"(#{a['rank']}위, 매칭: '{a['matched_negative']}')"
        )
    lines.append(f"\n확인 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    msg["Subject"] = "🚨 모다올 자동완성 부정 키워드 감지"
    msg["From"] = email_cfg["sender"]
    msg["To"] = email_cfg["recipient"]

    try:
        with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(email_cfg["sender"], email_cfg["password"])
            server.send_message(msg)
        print("  📧 이메일 알림 전송 완료")
    except Exception as e:
        print(f"  [오류] 이메일 전송 실패: {e}")


# ──────────────────────────────────────────────
# HTML 리포트
# ──────────────────────────────────────────────

def generate_report(config):
    """로그 데이터를 기반으로 HTML 리포트를 생성합니다."""
    log_dir = BASE_DIR / config["log_dir"]
    report_dir = BASE_DIR / config["report_dir"]
    report_dir.mkdir(exist_ok=True)

    # 모든 로그 파일 읽기
    log_files = sorted(log_dir.glob("check_*.json"))
    if not log_files:
        print("로그 데이터가 없습니다. 먼저 모니터링을 실행해주세요.")
        return

    history = []
    for lf in log_files:
        with open(lf, "r", encoding="utf-8") as f:
            history.append(json.load(f))

    # 부정 키워드 히스토리 추출
    neg_history = []
    for entry in history:
        ts = entry["timestamp"]
        for alert in entry.get("alerts", []):
            neg_history.append({**alert, "timestamp": ts})

    # 최신 상태
    latest = history[-1]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = report_dir / f"report_{timestamp}.html"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>모다올 자동완성 모니터링 리포트</title>
    <style>
        body {{ font-family: 'Malgun Gothic', sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f5f5f5; }}
        h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 10px; }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .alert {{ background: #fff3f3; border-left: 4px solid #e94560; }}
        .safe {{ background: #f0fff0; border-left: 4px solid #2ecc71; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th {{ background: #1a1a2e; color: white; padding: 10px; text-align: left; }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f9f9f9; }}
        .rank {{ font-weight: bold; color: #e94560; }}
        .platform {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        .naver {{ background: #03c75a; color: white; }}
        .google {{ background: #4285f4; color: white; }}
        .neg {{ color: #e94560; font-weight: bold; }}
        .timestamp {{ color: #888; font-size: 14px; }}
        .summary {{ display: flex; gap: 15px; flex-wrap: wrap; }}
        .stat {{ text-align: center; padding: 15px 25px; }}
        .stat-num {{ font-size: 32px; font-weight: bold; }}
        .stat-label {{ font-size: 13px; color: #666; margin-top: 5px; }}
    </style>
</head>
<body>
    <h1>모다올 자동완성 모니터링 리포트</h1>
    <p class="timestamp">생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 총 {len(history)}회 체크</p>

    <div class="summary">
        <div class="card stat">
            <div class="stat-num">{len(latest.get('alerts', []))}</div>
            <div class="stat-label">현재 부정 키워드</div>
        </div>
        <div class="card stat">
            <div class="stat-num">{len(neg_history)}</div>
            <div class="stat-label">누적 감지 횟수</div>
        </div>
        <div class="card stat">
            <div class="stat-num">{len(history)}</div>
            <div class="stat-label">총 모니터링 횟수</div>
        </div>
    </div>

    <h2>현재 자동완성 상태</h2>
"""

    for brand_kw, platforms in latest.get("suggestions", {}).items():
        for platform, terms in platforms.items():
            if not terms:
                continue
            platform_class = platform.lower()
            html += f"""
    <div class="card">
        <h3><span class="platform {platform_class}">{platform.upper()}</span> "{brand_kw}" 자동완성</h3>
        <table>
            <tr><th>순위</th><th>키워드</th><th>상태</th></tr>
"""
            neg_terms = config["negative_terms"]
            for rank, term in enumerate(terms, 1):
                is_neg = any(neg in term for neg in neg_terms)
                status = '<span class="neg">⚠️ 부정</span>' if is_neg else "✅ 정상"
                html += f'            <tr><td class="rank">#{rank}</td><td>{term}</td><td>{status}</td></tr>\n'
            html += "        </table>\n    </div>\n"

    if neg_history:
        html += """
    <h2>부정 키워드 감지 이력</h2>
    <div class="card alert">
        <table>
            <tr><th>시각</th><th>플랫폼</th><th>키워드</th><th>순위</th><th>매칭</th></tr>
"""
        for nh in reversed(neg_history[-50:]):
            ts_short = nh["timestamp"][:16].replace("T", " ")
            html += (
                f'            <tr><td>{ts_short}</td>'
                f'<td><span class="platform {nh["platform"]}">{nh["platform"].upper()}</span></td>'
                f'<td>{nh["suggestion"]}</td>'
                f'<td class="rank">#{nh["rank"]}</td>'
                f'<td class="neg">{nh["matched_negative"]}</td></tr>\n'
            )
        html += "        </table>\n    </div>\n"

    html += """
</body>
</html>"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n📊 리포트 생성 완료: {report_file}")
    return report_file


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────

def run_check(config):
    """1회 체크를 실행합니다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] 자동완성 모니터링 체크 시작...")

    suggestions = fetch_all_suggestions(config["brand_keywords"])

    # 현재 자동완성 결과 출력
    for brand_kw, platforms in suggestions.items():
        for platform, terms in platforms.items():
            if terms:
                print(f"\n  [{platform.upper()}] '{brand_kw}' 자동완성:")
                for i, term in enumerate(terms, 1):
                    print(f"    {i}. {term}")

    # 변화 감지 (이전 결과와 비교)
    changes = detect_changes(suggestions, config["log_dir"])

    # 부정 키워드 감지
    alerts = detect_negatives(suggestions, config["negative_terms"])

    # 로그 저장
    log_file = save_log(suggestions, alerts, config["log_dir"])
    print(f"\n  💾 로그 저장: {log_file}")

    # 알림 발송
    if config["alert"]["console"]:
        send_console_alert(alerts, changes)
    send_telegram_alert(alerts, config)
    send_email_alert(alerts, config)

    return alerts


def main():
    parser = argparse.ArgumentParser(description="모다올 자동완성 키워드 모니터링")
    parser.add_argument("--watch", action="store_true", help="주기적 반복 체크 모드")
    parser.add_argument("--report", action="store_true", help="HTML 리포트 생성")
    parser.add_argument("--interval", type=int, help="체크 간격 (분)")
    args = parser.parse_args()

    config = load_config()

    if args.report:
        generate_report(config)
        return

    if args.watch:
        interval = args.interval or config["check_interval_minutes"]
        print(f"🔍 모다올 자동완성 모니터링 시작 (간격: {interval}분)")
        print("   종료하려면 Ctrl+C를 누르세요.\n")
        try:
            while True:
                run_check(config)
                print(f"\n⏳ 다음 체크까지 {interval}분 대기...")
                time.sleep(interval * 60)
        except KeyboardInterrupt:
            print("\n\n모니터링을 종료합니다.")
    else:
        run_check(config)


if __name__ == "__main__":
    main()
