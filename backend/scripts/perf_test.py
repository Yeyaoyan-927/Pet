"""性能基线 + 并发防超卖复验（V8）。

用途
----
1. 给出**可对比的历史基线**：关键接口的 P50/P95/P99，便于以后判断"是不是变慢了"。
2. 在真实 HTTP 链路下复验并发防超卖（pytest 用的是进程内 TestClient，这里走真实网络栈）。

用法
----
```
python scripts/perf_test.py                       # 默认打 http://127.0.0.1:8000
python scripts/perf_test.py --rounds 30 --conc 8  # 默认每接口 20 次、并发 8
python scripts/perf_test.py --oversell            # 额外跑并发抢房（会建临时数据并清理）
```

说明：默认**不判定失败**，只输出基线；`--p95-threshold` 给了阈值才会在超标时返回非 0，
避免在不同机器上因环境差异产生假失败。
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
    return ordered[idx]


def load_credentials() -> dict[str, tuple[str, str]]:
    """复用冒烟脚本里的演示账号（不在此处保存密钥）。"""
    from scripts.chaos_test import load_demo_credentials

    return load_demo_credentials()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--rounds", type=int, default=20, help="每个接口采样次数")
    ap.add_argument("--conc", type=int, default=8, help="并发度")
    ap.add_argument("--p95-threshold", type=float, default=0, help="P95 阈值(ms)，0 表示不判定")
    ap.add_argument("--oversell", action="store_true", help="额外跑并发抢房（建临时数据，结束清理）")
    args = ap.parse_args()

    try:
        httpx.get(f"{args.base_url}/health", timeout=5)
    except Exception as exc:
        print(f"!! 无法连接 {args.base_url}：{exc}")
        print("   请先启动后端：uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return 2

    creds = load_credentials()
    if len(creds) < 3:
        print("!! 未找到演示账号凭据，请先执行 python scripts/init_db.py")
        return 2

    client = httpx.Client(base_url=args.base_url, timeout=30)

    def login(role: str) -> str:
        user, pwd = creds[role]
        r = client.post("/api/v1/auth/login", json={"username": user, "password": pwd})
        r.raise_for_status()
        return r.json()["data"]["access_token"]

    tokens = {role: login(role) for role in ("customer", "staff", "manager")}
    H = {role: {"Authorization": f"Bearer {t}"} for role, t in tokens.items()}

    # ---------- 1. 延迟基线 ----------
    targets = [
        ("GET", "/health", None),
        ("GET", "/api/v1/pets", "customer"),
        ("GET", "/api/v1/appointments?page=1&size=10", "customer"),
        ("GET", "/api/v1/messages?page=1&size=10", "customer"),
        ("GET", "/api/v1/boarding/rooms", "customer"),
        ("GET", "/api/v1/goods/products", "customer"),
        ("GET", "/api/v1/tasks", "manager"),
        ("GET", "/api/v1/boarding/dashboard?start=2026-01-01&end=2027-12-31", "manager"),
    ]

    print(f"\n{'接口':<56}{'P50':>8}{'P95':>8}{'P99':>8}{'状态':>8}")
    print("-" * 88)
    slow: list[tuple[str, float]] = []
    for method, path, role in targets:
        headers = H.get(role, {}) if role else {}
        # 预热一次，避免把首次建连计入基线
        client.request(method, path, headers=headers)
        samples: list[float] = []

        def once() -> float:
            started = time.perf_counter()
            resp = client.request(method, path, headers=headers)
            cost = (time.perf_counter() - started) * 1000
            return cost if resp.status_code < 500 else -1.0

        with ThreadPoolExecutor(max_workers=args.conc) as pool:
            for value in pool.map(lambda _: once(), range(args.rounds)):
                if value >= 0:
                    samples.append(value)
        ok_rate = len(samples) / args.rounds * 100
        p50, p95, p99 = pct(samples, 50), pct(samples, 95), pct(samples, 99)
        print(f"{path[:54]:<56}{p50:>8.1f}{p95:>8.1f}{p99:>8.1f}{ok_rate:>7.0f}%")
        if p95:
            slow.append((path, p95))

    # ---------- 2. 并发防超卖复验（可选） ----------
    exit_code = 0
    if args.oversell:
        print("\n== 并发抢房：同一房舍 + 同一区间，6 并发只允许成功 1 单 ==")
        tag = random.randint(10000, 99999)
        pet_id = room_id = None
        try:
            r = client.post("/api/v1/pets", headers=H["customer"], json={
                "name": f"压测犬{tag}", "species": "dog", "gender": "male",
                "weight": 8.0, "sterilized": 1,
            })
            pet_id = r.json()["data"]["id"]

            check_in = date.today() + timedelta(days=200)
            check_out = check_in + timedelta(days=3)
            # 疫苗是寄养硬门槛：有效期必须覆盖入住当天
            client.post(f"/api/v1/pets/{pet_id}/vaccines", headers=H["customer"], json={
                "record_type": "vaccine", "name": "狂犬疫苗",
                "record_date": str(date.today()), "next_date": str(check_in + timedelta(days=30)),
            })

            r = client.post("/api/v1/boarding/rooms", headers=H["manager"], json={
                "room_no": f"P{tag}", "room_type": "standard", "name": "压测房",
                "species_limit": "all", "weight_limit": 30, "ratio_percent": 100, "capacity": 1,
            })
            r.raise_for_status()
            room_id = r.json()["data"]["id"]

            def book(i: int) -> int:
                resp = client.post("/api/v1/boarding/orders", headers=H["customer"], json={
                    "pet_id": pet_id, "room_id": room_id,
                    "check_in_date": str(check_in), "check_out_date": str(check_out),
                    "terms_confirmed": True, "idempotent_key": f"perf-{tag}-{i}",
                })
                return resp.status_code

            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=6) as pool:
                codes = list(pool.map(book, range(6)))
            cost = (time.perf_counter() - started) * 1000
            success = codes.count(200)
            passed = success == 1
            print(f"  成功 {success} 单 / 拒绝 {codes.count(409)} 单（{cost:.0f} ms）"
                  f" → {'PASS' if passed else 'FAIL'}  {codes}")
            if not passed:
                exit_code = 1
        finally:
            # 清理：删宠物（逻辑删除）+ 房舍转维护，避免污染演示数据
            if pet_id:
                client.delete(f"/api/v1/pets/{pet_id}", headers=H["customer"])
            if room_id:
                client.patch(f"/api/v1/boarding/rooms/{room_id}/status",
                             headers=H["manager"], json={"status": "maintenance"})
            print("  （临时宠物与房舍已清理）")

    # ---------- 3. 阈值判定 ----------
    if args.p95_threshold > 0:
        over = [(p, v) for p, v in slow if v > args.p95_threshold]
        if over:
            print(f"\n!! P95 超过阈值 {args.p95_threshold} ms：")
            for path, value in over:
                print(f"   - {path}  {value:.1f} ms")
            exit_code = 1
        else:
            print(f"\nP95 全部低于阈值 {args.p95_threshold} ms ✅")

    client.close()
    print("\n提示：本脚本输出的是**相对基线**，同一台机器上前后对比才有意义。")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
