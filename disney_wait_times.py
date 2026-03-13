#!/usr/bin/env python3
"""
Tokyo Disney Wait Time Average Chart Generator
================================================
從 Queue-Times.com 抓取東京迪士尼海洋遊樂設施的歷史逐時等候時間，
計算每個時間點的平均值（wait=0 視為關閉/暫停，忽略不計），輸出成 CSV。

用法:
    python disney_wait_times.py           # 正常執行
    python disney_wait_times.py --list    # 列出公園內所有遊樂設施 ID
"""

import argparse
import csv
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
#  CONFIG — 在這裡修改設定
# ============================================================
CONFIG = {
    # 公園 ID：274 = 東京迪士尼樂園，275 = 東京迪士尼海洋
    "park_id": 275,

    # 抓取範圍：往前幾天 (x-1 ~ x-N)
    "days_back": 4,

    # 時間精度：每幾分鐘一個 bucket（向下取整）
    "time_precision_minutes": 5,

    # 輸出 CSV 路徑
    "output_file": "disney_wait_times_avg.csv",

    # 目標遊樂設施清單（東京迪士尼海洋）
    # dpa_cutoff: 中午 12:00 後，等候時間低於此值視為 DPA 專用（當成 0 忽略）
    #             設為 None 代表不套用此規則
    "rides": [
        {"id": 8023,  "name": "Toy Story Mania!",                    "dpa_cutoff": 70},
        {"id": 8024,  "name": "Soaring: Fantastic Flight",           "dpa_cutoff": 80},
        {"id": 13559, "name": "Anna and Elsa's Frozen Journey",      "dpa_cutoff": 60},
        {"id": 13560, "name": "Rapunzel's Lantern Festival",         "dpa_cutoff": 20},
        {"id": 13561, "name": "Peter Pan's Never Land Adventure",    "dpa_cutoff": 10},
        {"id": 8047,  "name": "Tower of Terror",                     "dpa_cutoff": 80},
        {"id": 8028,  "name": "Journey to the Center of the Earth",  "dpa_cutoff": 100},
        {"id": 8046,  "name": "Raging Spirits",                      "dpa_cutoff": 50},
    ],
}
# ============================================================

BASE_URL = "https://queue-times.com"
REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ------------------------------------------------------------------
# 抓取 & 解析歷史資料
# ------------------------------------------------------------------

def fetch_ride_history(
    sess: requests.Session,
    park_id: int,
    ride_id: int,
    date_str: str,
) -> list[dict]:
    """
    抓取特定設施某一天的逐時等候時間。
    資料嵌在 HTML 的 Chartkick LineChart script 裡（chart-1，Reported by park）。
    回傳 list of {"time": datetime, "wait": int}，wait=0 已過濾。
    """
    url = f"{BASE_URL}/parks/{park_id}/rides/{ride_id}?given_date={date_str}"
    r = sess.get(url, timeout=15)
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {url}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    for script in soup.find_all("script"):
        text = script.string or ""
        # 找 chart-1 的 LineChart（逐時資料）
        if 'chart-1' not in text:
            continue

        # 抓 "Reported by park" 的 data 陣列
        # 格式：["MM/DD/YY HH:MM:SS","wait"]
        pattern = r'"Reported by park".*?"data"\s*:\s*(\[\[.*?\]\])'
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            continue

        raw_arr = match.group(1)
        # 解析所有 ["timestamp", "value"] 對
        pairs = re.findall(r'\["([^"]+)"\s*,\s*"([\d.]+)"\]', raw_arr)

        records = []
        for ts_str, wait_str in pairs:
            wait = float(wait_str)
            try:
                dt = datetime.strptime(ts_str, "%m/%d/%y %H:%M:%S")
                records.append({"time": dt, "wait": int(wait)})
            except ValueError:
                print(f"  [WARN] 無法解析時間: {ts_str!r}", file=sys.stderr)

        return records

    return []


# ------------------------------------------------------------------
# 時間工具
# ------------------------------------------------------------------

def floor_to_precision(dt: datetime, precision: int) -> str:
    """將 datetime 向下取整到最近的 precision 分鐘，回傳 'HH:MM' 字串。"""
    total   = dt.hour * 60 + dt.minute
    floored = (total // precision) * precision
    return f"{floored // 60:02d}:{floored % 60:02d}"


# ------------------------------------------------------------------
# 核心邏輯
# ------------------------------------------------------------------

def compute_averages(config: dict) -> dict[str, dict[str, float]]:
    park_id   = config["park_id"]
    days_back = config["days_back"]
    precision = config["time_precision_minutes"]
    rides     = config["rides"]

    today = date.today()
    dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(1, days_back + 1)
    ]

    print(f"公園 ID : {park_id}")
    print(f"日期範圍: {dates[-1]} ~ {dates[0]}  （共 {days_back} 天）")
    print(f"時間精度: {precision} 分鐘")
    print(f"設施數量: {len(rides)}")
    print("=" * 50)

    sess = requests.Session()
    sess.headers.update(HEADERS)

    results: dict[str, dict[str, float]] = {}

    for ride in rides:
        ride_id   = ride["id"]
        ride_name = ride["name"]
        print(f"\n► {ride_name}  (id={ride_id})")

        # slot -> [wait_time, ...]
        bucket: dict[str, list[int]] = defaultdict(list)

        for date_str in dates:
            all_records = fetch_ride_history(sess, park_id, ride_id, date_str)
            time.sleep(REQUEST_DELAY)

            dpa_cutoff = ride.get("dpa_cutoff")  # 中午後低於此值視為 DPA 專用
            valid_cnt = 0
            skipped_cnt = 0
            dpa_cnt = 0
            for rec in all_records:
                wait = rec["wait"]
                dt   = rec["time"]

                # 原本就是 0 → 暫停
                if wait == 0:
                    skipped_cnt += 1
                    continue

                # 中午 12:00 後，低於 dpa_cutoff → 視為 DPA 專用，當 0 處理
                if dpa_cutoff is not None and dt.hour >= 12 and wait < dpa_cutoff:
                    dpa_cnt += 1
                    continue

                slot = floor_to_precision(dt, precision)
                bucket[slot].append(wait)
                valid_cnt += 1

            dpa_msg = f", DPA忽略 {dpa_cnt} 筆" if dpa_cnt else ""
            print(f"  {date_str}: 有效 {valid_cnt} 筆, 暫停(wait=0) {skipped_cnt} 筆已忽略{dpa_msg}")

        results[ride_name] = {
            slot: round(sum(vals) / len(vals), 1)
            for slot, vals in sorted(bucket.items())
        }
        print(f"  → {len(results[ride_name])} 個時間 bucket")

    return results


# ------------------------------------------------------------------
# CSV 輸出
# ------------------------------------------------------------------

def write_csv(results: dict[str, dict[str, float]], output_file: str) -> None:
    ride_names = list(results.keys())
    all_slots  = sorted(set(slot for rd in results.values() for slot in rd))

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Time (HH:MM)"] + ride_names)
        for slot in all_slots:
            row = [slot] + [results[name].get(slot, "") for name in ride_names]
            writer.writerow(row)

    print(f"\n✅ CSV 已輸出至: {output_file}")
    print(f"   共 {len(all_slots)} 個時間點 × {len(ride_names)} 個設施")


# ------------------------------------------------------------------
# --list 輔助功能
# ------------------------------------------------------------------

def cmd_list_rides(park_id: int) -> None:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    print(f"正在查詢公園 {park_id} 的設施清單...")
    r = sess.get(f"{BASE_URL}/parks/{park_id}/queue_times.json", timeout=15)
    if r.status_code != 200:
        print(f"查詢失敗 (HTTP {r.status_code})")
        return
    data = r.json()

    rides = []
    if isinstance(data, dict):
        for land in data.get("lands", []):
            rides.extend(land.get("rides", []))
        rides.extend(data.get("rides", []))
    elif isinstance(data, list):
        rides = data

    if not rides:
        print("沒有資料。")
        return

    print(f"\n{'ID':>6}  名稱")
    print("-" * 50)
    for ride in sorted(rides, key=lambda r: r.get("id", 0)):
        print(f"{ride.get('id', '?'):>6}  {ride.get('name', '(unknown)')}")
    print(f"\n共 {len(rides)} 個設施")


# ------------------------------------------------------------------
# 主程式
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tokyo Disney 等候時間平均值抓取工具")
    parser.add_argument("--list", action="store_true", help="列出公園所有設施 ID")
    parser.add_argument("--park", type=int, default=None, help="覆寫 park_id（僅 --list 用）")
    args = parser.parse_args()

    if args.list:
        cmd_list_rides(args.park or CONFIG["park_id"])
        return

    results = compute_averages(CONFIG)

    if not any(results.values()):
        print("\n⚠️  沒有取得任何有效資料。")
        sys.exit(1)

    write_csv(results, CONFIG["output_file"])

    print("\n── 摘要 ──")
    for name, data in results.items():
        if data:
            overall = sum(data.values()) / len(data)
            peak    = max(data, key=data.get)
            print(f"  {name}: 全日均 {overall:.1f} 分, 高峰 {peak} ({data[peak]:.0f} 分)")
        else:
            print(f"  {name}: 無資料")


if __name__ == "__main__":
    main()