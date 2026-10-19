"""Matplotlib grafiklari (Qt ichida): tarix bo'linishi, kapital egri chizig'i, oylik natija, o'rganish tarixi, jonli R.
Har grafikda sichqoncha ostida vertikal chiziq + qiymat oynasi (hover) bor."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtWidgets import QSizePolicy  # noqa: E402

from . import data as D  # noqa: E402
from . import theme  # noqa: E402

SEG_NAME = {"train": "O'rganish (train)", "val": "Validatsiya", "test": "Holdout (tegilmagan)"}
MODE_SLOT = {"genetic": "train", "optimizer": "val", "ml": "test"}     # rejim identifikatsiyasi: kategorik 1/2/3


class Chart(FigureCanvasQTAgg):
    def __init__(self, height: float = 3.0, parent=None):
        self.fig = Figure(figsize=(6, height), dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(int(height * 80))
        self.ax = self.fig.add_subplot(111)
        self._hover: List[tuple] = []                 # (x_num, y, matn_funksiyasi(i))
        self._vline = None
        self._tip = None
        self._key = None
        self.mpl_connect("motion_notify_event", self._on_move)
        self.mpl_connect("figure_leave_event", lambda _e: self._hide())

    def need(self, key) -> bool:
        """Ma'lumot o'zgarmagan bo'lsa qayta chizmaslik uchun (mavzu almashganda _key tozalanadi)."""
        if key == self._key:
            return False
        self._key = key
        return True

    # ------------------------------------------------------------ uslub
    def style(self) -> None:
        p = theme.current()
        self.fig.set_facecolor(p["surface"])
        ax = self.ax
        ax.set_facecolor(p["surface"])
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(p["axis"])
        ax.tick_params(colors=p["muted"], labelsize=8.5, length=0)
        ax.grid(True, axis="y", color=p["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        self._vline, self._tip = None, None

    def begin(self) -> Any:
        self.ax.clear()
        self._hover = []
        self.style()
        return self.ax

    def empty(self, text: str) -> None:
        ax = self.begin()
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        ax.spines["bottom"].set_visible(False)
        ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", color=theme.c("muted"), fontsize=10,
                wrap=True)
        self.draw_idle()

    def finish(self) -> None:
        try:
            self.fig.tight_layout(pad=0.6)
        except Exception:  # noqa: BLE001
            pass
        self.draw_idle()

    def date_axis(self) -> None:
        loc = mdates.AutoDateLocator(minticks=3, maxticks=8)
        self.ax.xaxis.set_major_locator(loc)
        self.ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))

    # ------------------------------------------------------------ hover
    def add_hover(self, x: np.ndarray, y: np.ndarray, text: Callable[[int], str]) -> None:
        if len(x):
            self._hover.append((np.asarray(x, dtype=float), np.asarray(y, dtype=float), text))

    def _hide(self) -> None:
        if self._vline is not None and self._vline.get_visible():
            self._vline.set_visible(False)
            self._tip.set_visible(False)
            self.draw_idle()

    def _on_move(self, e) -> None:
        if e.inaxes is not self.ax or not self._hover or e.xdata is None:
            self._hide()
            return
        best = None
        for xs, ys, fn in self._hover:
            i = int(np.clip(np.searchsorted(xs, e.xdata), 0, len(xs) - 1))
            if i > 0 and abs(xs[i - 1] - e.xdata) < abs(xs[i] - e.xdata):
                i -= 1
            dpx = abs(self.ax.transData.transform((xs[i], ys[i]))[0] - e.x)
            if best is None or dpx < best[0]:
                best = (dpx, xs[i], ys[i], fn(i))
        if best is None or best[0] > 40:
            self._hide()
            return
        p = theme.current()
        if self._vline is None:
            self._vline = self.ax.axvline(best[1], color=p["muted"], linewidth=1, zorder=5)
            self._tip = self.ax.annotate("", xy=(0, 0), xytext=(12, 12), textcoords="offset points", fontsize=9,
                                         color=p["text"], zorder=10,
                                         bbox=dict(boxstyle="round,pad=0.5", fc=p["surface"], ec=p["border"]))
        self._vline.set_xdata([best[1], best[1]])
        self._vline.set_visible(True)
        self._tip.xy = (best[1], best[2])
        self._tip.set_text(best[3])
        # oyna o'ng chetdan chiqmasin
        frac = (e.x - self.ax.bbox.x0) / max(1, self.ax.bbox.width)
        self._tip.set_position((-150 if frac > 0.6 else 12, 12))
        self._tip.set_visible(True)
        self.draw_idle()


def _num(idx) -> np.ndarray:
    return mdates.date2num(pd.DatetimeIndex(idx).to_pydatetime())


class PriceSplitChart(Chart):
    """Tarix narxi + train / validatsiya / holdout zonalari (zonalar ustida to'g'ridan-to'g'ri yozuv)."""

    def show(self, df: Optional[pd.DataFrame], bounds: Optional[Dict[str, List[str]]] = None, title: str = "") -> None:
        if df is None or not len(df):
            self.empty("Tarix fayli tanlanmagan yoki o'qib bo'lmadi")
            return
        p = theme.current()
        ax = self.begin()
        if bounds is None:
            n = len(df)
            a, b = int(n * 0.6), int(n * 0.8)
            bounds = {"train": [df.index[0], df.index[a]], "val": [df.index[a], df.index[b]], "test": [df.index[b], df.index[-1]]}
        for k, (s, e) in bounds.items():
            s, e = mdates.date2num(pd.Timestamp(s)), mdates.date2num(pd.Timestamp(e))
            ax.axvspan(s, e, color=p[k], alpha=0.10, linewidth=0)
            ax.text(s + (e - s) / 2, 1.0, SEG_NAME.get(k, k), transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                    fontsize=8.5, color=p["text2"])
        x = _num(df.index)
        ax.plot(x, df["close"].values, color=p["price"], linewidth=1.2)
        ax.xaxis_date()
        self.date_axis()
        closes = df["close"].values
        bnd = {k: (pd.Timestamp(v[0]), pd.Timestamp(v[1])) for k, v in bounds.items()}

        def tip(i: int) -> str:
            t = df.index[i]
            seg = next((SEG_NAME[k] for k, (s, e) in bnd.items() if s <= t <= e), "")
            return "%s\nNarx: %.2f\n%s" % (t.strftime("%Y-%m-%d %H:%M"), closes[i], seg)
        self.add_hover(x, closes, tip)
        self.finish()


class EquityChart(Chart):
    """Har bitimdan keyingi jami R (kapital egri chizig'i) — segmentlar bo'yicha rang."""

    def show(self, rep: Optional[Dict[str, Any]]) -> List[tuple]:
        if not rep or not rep.get("curves"):
            self.empty("Bitimlar egri chizig'i yo'q — avval o'rganishni ishga tushiring")
            return []
        p = theme.current()
        ax = self.begin()
        segs = ["test"] if rep.get("mode") == "optimizer" else ["train", "val", "test"]
        base = 0.0
        legend = []
        for s in segs:
            f = D.curve_frame(rep, s)
            if f is None:
                continue
            cum = base + f["r"].cumsum().values
            xn = _num(f.index)
            # oldingi segment oxiridan uzluksiz davom etadi
            xs = np.concatenate([[xn[0]], xn])
            ys = np.concatenate([[base], cum])
            ax.plot(xs, ys, color=p[s], linewidth=2)
            ax.axvspan(xn[0], xn[-1], color=p[s], alpha=0.06, linewidth=0)
            name = "Walk-forward OOS" if rep.get("mode") == "optimizer" else SEG_NAME[s]
            legend.append((name, p[s], "line"))
            r, ix = f["r"].values, f.index

            def tip(i: int, r=r, ix=ix, cum=cum, name=name) -> str:
                return "%s\n%s\nBitim: %+.2fR\nJami: %+.1fR" % (name, ix[i].strftime("%Y-%m-%d"), r[i], cum[i])
            self.add_hover(xn, cum, tip)
            base = float(cum[-1])
        ax.axhline(0, color=p["axis"], linewidth=1)
        ax.set_ylabel("Jami natija, R", color=p["muted"], fontsize=9)
        ax.xaxis_date()
        self.date_axis()
        self.finish()
        return legend


class SegmentBars(Chart):
    """Segmentlar bo'yicha o'rtacha natija (kutilma, R) va darvoza chegarasi."""

    def show(self, rep: Optional[Dict[str, Any]], need: float = 0.05) -> None:
        segs = (rep or {}).get("segments") or {}
        order = [k for k in ("train", "val", "test") if k in segs]
        if not order:
            self.empty("Natija yo'q")
            return
        p = theme.current()
        ax = self.begin()
        names = ["Train" if k == "train" else "Validatsiya" if k == "val" else
                 ("OOS" if rep.get("mode") == "optimizer" else "Holdout") for k in order]
        vals = [segs[k].get("exp", 0.0) for k in order]
        xs = np.arange(len(order))
        ax.bar(xs, vals, width=0.5, color=[p[k] for k in order], edgecolor=p["surface"], linewidth=2)
        ax.axhline(0, color=p["axis"], linewidth=1)
        ax.axhline(need, color=p["text2"], linewidth=1, linestyle=(0, (4, 3)))
        ax.text(-0.98, need, "chegara %+.2fR" % need, va="bottom", ha="left", fontsize=8, color=p["text2"])
        for x, v, k in zip(xs, vals, order):
            ax.text(x, v, "%+.3fR\n%d bitim" % (v, segs[k].get("n", 0)), ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=8.5, color=p["text"])
        ax.set_xticks(xs, names)
        ax.set_xlim(-1.0, len(order) - 0.4)
        lo, hi = min(0, min(vals), need), max(0, max(vals), need)
        pad = (hi - lo) * 0.35 + 0.02
        ax.set_ylim(lo - pad * (0.6 if lo < 0 else 0.2), hi + pad)
        self.add_hover(xs.astype(float), np.asarray(vals),
                       lambda i: "%s\nn=%d  win %.0f%%\nkutilma %+.3fR\nPF %.2f  t %.2f\nmaks. pasayish %.1fR" % (
                           names[i], segs[order[i]].get("n", 0), segs[order[i]].get("win", 0) * 100,
                           segs[order[i]].get("exp", 0), segs[order[i]].get("pf", 0), segs[order[i]].get("t", 0),
                           segs[order[i]].get("dd", 0)))
        self.finish()


class MonthlyChart(Chart):
    """Oylik R yig'indisi: musbat — ko'k, manfiy — qizil (ishora uchun ikki qutbli palitra)."""

    def show(self, rep: Optional[Dict[str, Any]]) -> None:
        m = D.monthly_r(rep or {}, ("test",) if (rep or {}).get("mode") == "optimizer" else ("train", "val", "test"))
        if not len(m):
            self.empty("Oylik natija yo'q")
            return
        p = theme.current()
        ax = self.begin()
        x = mdates.date2num(pd.DatetimeIndex(m["month"]).to_pydatetime())
        cols = [p["pos"] if v >= 0 else p["neg"] for v in m["r"]]
        ax.bar(x, m["r"].values, width=24, color=cols, edgecolor=p["surface"], linewidth=1)
        ax.axhline(0, color=p["axis"], linewidth=1)
        ax.xaxis_date()
        self.date_axis()
        ax.set_ylabel("Oylik R", color=p["muted"], fontsize=9)
        segn = {"train": "Train", "val": "Validatsiya", "test": "Holdout"}
        self.add_hover(x, m["r"].values, lambda i: "%s\n%+.1fR  (%s)" % (
            pd.Timestamp(m["month"].iloc[i]).strftime("%Y-%m"), m["r"].iloc[i], segn.get(m["seg"].iloc[i], "")))
        self.finish()


class LearnHistoryChart(Chart):
    """Har o'rganish sikli: holdout kutilmasi. Rang — rejim; to'liq nuqta — darvozadan o'tgan, bo'sh — o'tmagan."""

    def show(self, rows: List[Dict[str, Any]], need: float = 0.05) -> List[tuple]:
        pts = [(i, r) for i, r in enumerate(rows) if (r.get("segments") or {}).get("test")]
        if not pts:
            self.empty("Hali o'rganish natijalari yo'q")
            return []
        p = theme.current()
        ax = self.begin()
        legend = []
        for mode in ("genetic", "optimizer", "ml"):
            sel = [(i, r) for i, r in pts if r.get("mode") == mode]
            if not sel:
                continue
            col = p[MODE_SLOT[mode]]
            legend.append((mode, col))
            xs = np.array([i + 1 for i, _ in sel], dtype=float)
            ys = np.array([r["segments"]["test"].get("exp", 0.0) for _, r in sel])
            ok = np.array([bool(r.get("passed")) for _, r in sel])
            ax.scatter(xs[ok], ys[ok], s=70, color=col, edgecolors=p["surface"], linewidths=2, zorder=3)
            ax.scatter(xs[~ok], ys[~ok], s=70, facecolors=p["surface"], edgecolors=col, linewidths=2, zorder=3)

            def tip(i: int, sel=sel) -> str:
                r = sel[i][1]
                te = r["segments"]["test"]
                return "%s · %s\nholdout %+.3fR, n=%d, t=%.2f\n%s" % (
                    r.get("time", ""), r.get("mode"), te.get("exp", 0), te.get("n", 0), te.get("t", 0),
                    "✓ darvozadan o'tdi" if r.get("passed") else "✕ o'tmadi")
            self.add_hover(xs, ys, tip)
        ax.axhline(0, color=p["axis"], linewidth=1)
        ax.axhline(need, color=p["text2"], linewidth=1, linestyle=(0, (4, 3)))
        ax.text(ax.get_xlim()[1], need, "chegara ", ha="right", va="bottom", fontsize=8, color=p["text2"])
        ax.set_xlabel("O'rganish sikli №", color=p["muted"], fontsize=9)
        ax.set_ylabel("Holdout kutilma, R", color=p["muted"], fontsize=9)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        self.finish()
        return legend


class LiveRChart(Chart):
    """Jonli bitimlar: har bitim R (ustun) va jami (chiziq) — bitta o'q, bir xil birlik (R)."""

    def show(self, rs: Sequence[float], kill_sum: float, window: int) -> None:
        if not rs:
            self.empty("Jonli yopilgan bitimlar hali yo'q")
            return
        p = theme.current()
        ax = self.begin()
        r = np.asarray(rs, dtype=float)
        x = np.arange(1, len(r) + 1)
        ax.bar(x, r, width=0.7, color=[p["pos"] if v >= 0 else p["neg"] for v in r], edgecolor=p["surface"])
        roll = np.array([r[max(0, i - window + 1):i + 1].sum() for i in range(len(r))])
        ax.plot(x, roll, color=p["text2"], linewidth=2)
        ax.axhline(kill_sum, color=p["critical"], linewidth=1.2, linestyle=(0, (4, 3)))
        ax.text(0.6, kill_sum, " kill-switch %.1fR" % kill_sum, va="bottom", fontsize=8, color=p["text2"])
        ax.axhline(0, color=p["axis"], linewidth=1)
        ax.set_xlabel("Bitim №", color=p["muted"], fontsize=9)
        self.add_hover(x.astype(float), roll, lambda i: "Bitim %d: %+.2fR\nOxirgi %d bitim yig'indisi: %+.1fR" % (
            i + 1, r[i], window, roll[i]))
        self.finish()


class ProgressChart(Chart):
    """O'rganish jarayoni: eng yaxshi train baho (t) qadamlar bo'yicha."""

    def show(self, xs: Sequence[float], ys: Sequence[float], xlabel: str = "qadam") -> None:
        if not xs:
            self.empty("O'rganish boshlanishi kutilmoqda…")
            return
        p = theme.current()
        ax = self.begin()
        ax.plot(xs, ys, color=p["accent"], linewidth=2, marker="o", markersize=3)
        ax.set_xlabel(xlabel, color=p["muted"], fontsize=9)
        ax.set_ylabel("eng yaxshi train t", color=p["muted"], fontsize=9)
        self.add_hover(np.asarray(xs, float), np.asarray(ys, float), lambda i: "%s %d\nbaho %.2f" % (xlabel, xs[i], ys[i]))
        self.finish()
