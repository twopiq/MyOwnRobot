"""Buyruq qatori: ilovasiz ishlatish (CI va tajriba uchun).

  python -m mor.cli import FAYL.csv [--symbol XAUUSD] [--tf M15]
  python -m mor.cli train [--epochs 50] [--tf M15] [--symbols XAUUSD,EURUSD]
  python -m mor.cli info
"""
from __future__ import annotations

import argparse
import json
import sys

from . import importers, paths
from .db import Database
from .trainer import TrainCfg, Trainer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import")
    a.add_argument("file")
    a.add_argument("--symbol")
    a.add_argument("--tf")
    a.add_argument("--target-tf")
    t = sub.add_parser("train")
    t.add_argument("--epochs", type=int, default=50)
    t.add_argument("--envs", type=int, default=16)
    t.add_argument("--tf", default="M15")
    t.add_argument("--symbols", default="")
    t.add_argument("--max-seconds", type=float, default=0)
    t.add_argument("--no-resume", action="store_true")
    g = sub.add_parser("signal")
    g.add_argument("--tf", default="M15")
    g.add_argument("--symbols", default="")
    sub.add_parser("info")
    args = ap.parse_args(argv)
    db = Database(paths.db_path())
    if args.cmd == "import":
        print(json.dumps(importers.import_csv(db, args.file, args.symbol, args.tf, args.target_tf), ensure_ascii=False))
    elif args.cmd == "train":
        cfg = TrainCfg(tf=args.tf, symbols=[s for s in args.symbols.upper().split(",") if s], epochs=args.epochs, envs=args.envs,
                       max_seconds=args.max_seconds, resume=not args.no_resume)

        def ev(e):
            if e["type"] == "log":
                print(e["msg"], flush=True)
            elif e["type"] == "epoch" and "val" in e:
                print("epoxa %d/%d val %+.3fR (n=%d)" % (e["epoch"], e["epochs"], e["val"]["exp"], e["val"]["n"]), flush=True)
        m = Trainer(db, cfg, ev).run()
        print(json.dumps({k: m[k] for k in ("val", "test", "test_guard", "gate_ok", "gate")}, ensure_ascii=False, default=float))
    elif args.cmd == "signal":
        from . import signal as sg
        from .trainer import load_series
        rows = sg.check_all(load_series(db, TrainCfg(tf=args.tf, symbols=[x for x in args.symbols.upper().split(",") if x])))
        print(json.dumps({"rows": rows, "advice": sg.advice(rows)}, ensure_ascii=False, default=float))
    else:
        print(json.dumps({"datasets": db.datasets(), "experiences": db.experience_stats(), "policy": db.latest_policy()},
                         ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
