"""DQN agenti (faqat numpy — yengil, torch kerak emas): Double DQN, dueling-siz MLP, Adam, ustuvorlikli tajriba xotirasi.

Xotira uchta oqimdan o'rnak oladi:
  • oddiy tajriba — ustuvorligi TD-xatosiga (agent qayerda adashayotganiga) proporsional;
  • "namuna" — foydali bitimlarning o'tishlari (R >= elite_r) — ulardan doimiy ulush bilan qayta o'rganadi;
  • "xato" — katta zarar bilan tugagan bitimlarning o'tishlari (R <= mistake_r) — ulardan ham doimiy ulush bilan.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

from .env import N_ACTIONS, OBS_DIM

NORMAL, ELITE, MISTAKE = 0, 1, 2


class MLP:
    def __init__(self, sizes: Tuple[int, ...], rng: np.random.Generator):
        self.W, self.b = [], []
        for i in range(len(sizes) - 1):
            self.W.append((rng.standard_normal((sizes[i], sizes[i + 1])) * np.sqrt(2.0 / sizes[i])).astype(np.float32))
            self.b.append(np.zeros(sizes[i + 1], dtype=np.float32))
        self.W[-1] *= 0.1
        self.m = [np.zeros_like(p) for p in self.W + self.b]
        self.v = [np.zeros_like(p) for p in self.W + self.b]
        self.step_n = 0

    def params(self):
        return self.W + self.b

    def forward(self, x: np.ndarray, cache: bool = False):
        hs = [x]
        for i in range(len(self.W) - 1):
            x = np.maximum(x @ self.W[i] + self.b[i], 0.0)
            hs.append(x)
        out = x @ self.W[-1] + self.b[-1]
        return (out, hs) if cache else out

    def backward_adam(self, hs, dout: np.ndarray, lr: float, clip: float = 5.0) -> None:
        grads_W, grads_b = [None] * len(self.W), [None] * len(self.W)
        d = dout
        for i in range(len(self.W) - 1, -1, -1):
            grads_W[i] = hs[i].T @ d
            grads_b[i] = d.sum(0)
            if i > 0:
                d = (d @ self.W[i].T) * (hs[i] > 0)
        grads = grads_W + grads_b
        norm = float(np.sqrt(sum(float((g ** 2).sum()) for g in grads)))
        if norm > clip:
            grads = [g * (clip / norm) for g in grads]
        self.step_n += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        c1, c2 = 1 - b1 ** self.step_n, 1 - b2 ** self.step_n
        for p, g, m, v in zip(self.params(), grads, self.m, self.v):
            m *= b1
            m += (1 - b1) * g
            v *= b2
            v += (1 - b2) * g * g
            p -= lr * (m / c1) / (np.sqrt(v / c2) + eps)

    def copy_from(self, other: "MLP", tau: float = 1.0) -> None:
        for p, q in zip(self.params(), other.params()):
            p *= (1 - tau)
            p += tau * q

    def state(self) -> Dict[str, np.ndarray]:
        return {("W%d" % i): w for i, w in enumerate(self.W)} | {("b%d" % i): b for i, b in enumerate(self.b)}

    def load_state(self, d: Dict[str, np.ndarray]) -> None:
        for i in range(len(self.W)):
            self.W[i][...] = d["W%d" % i]
            self.b[i][...] = d["b%d" % i]


class Replay:
    def __init__(self, cap: int, obs_dim: int = OBS_DIM, alpha: float = 0.6):
        self.cap, self.alpha = cap, alpha
        self.o = np.zeros((cap, obs_dim), np.float32)
        self.o2 = np.zeros((cap, obs_dim), np.float32)
        self.a = np.zeros(cap, np.int64)
        self.r = np.zeros(cap, np.float32)
        self.d = np.zeros(cap, np.float32)
        self.pr = np.zeros(cap, np.float32)
        self.tag = np.zeros(cap, np.int8)
        self.n = 0
        self.ptr = 0

    def add(self, o, a, r, o2, d) -> int:
        i = self.ptr
        self.o[i], self.a[i], self.r[i], self.o2[i], self.d[i] = o, a, r, o2, d
        self.pr[i] = self.pr[:self.n].max() if self.n else 1.0
        self.tag[i] = NORMAL
        self.ptr = (i + 1) % self.cap
        self.n = min(self.n + 1, self.cap)
        return i

    def mark(self, idx, tag: int) -> None:
        for i in idx:
            self.tag[i] = tag
            self.pr[i] = max(self.pr[i], 1.0)

    def counts(self) -> Dict[str, int]:
        t = self.tag[:self.n]
        return {"normal": int((t == NORMAL).sum()), "elite": int((t == ELITE).sum()), "mistake": int((t == MISTAKE).sum())}

    def sample(self, bs: int, rng: np.random.Generator, share_elite: float = 0.1, share_mistake: float = 0.1,
               beta: float = 0.4) -> Tuple[np.ndarray, np.ndarray]:
        n = self.n
        tags = self.tag[:n]
        idx = []
        for tg, share in ((ELITE, share_elite), (MISTAKE, share_mistake)):
            pool = np.flatnonzero(tags == tg)
            k = int(round(bs * share))
            if len(pool) and k:
                idx.append(rng.choice(pool, size=min(k, len(pool)), replace=len(pool) < k))
        rest = bs - sum(len(x) for x in idx)
        p = (self.pr[:n] + 1e-3) ** self.alpha
        p /= p.sum()
        idx.append(rng.choice(n, size=rest, p=p))
        idx = np.concatenate(idx)
        w = (n * p[idx]) ** (-beta)
        return idx, (w / w.max()).astype(np.float32)


class Agent:
    def __init__(self, hidden: Tuple[int, ...] = (128, 128), lr: float = 3e-4, gamma: float = 0.99, seed: int = 0,
                 obs_dim: int = OBS_DIM):
        self.rng = np.random.default_rng(seed)
        self.sizes = (obs_dim,) + tuple(hidden) + (N_ACTIONS,)
        self.q = MLP(self.sizes, self.rng)
        self.target = MLP(self.sizes, self.rng)
        self.target.copy_from(self.q)
        self.lr, self.gamma = lr, gamma
        self.updates = 0
        self.last_loss = 0.0

    # ------------------------------------------------------------ qaror
    def q_values(self, obs: np.ndarray) -> np.ndarray:
        return self.q.forward(np.atleast_2d(obs).astype(np.float32))

    @staticmethod
    def mask_from_obs(obs: np.ndarray, n_feat: int) -> np.ndarray:
        """Pozitsiya bor → faqat KUTISH/YOPISH; yo'q → KUTISH/BUY/SELL."""
        flat = obs[:, n_feat] == 0
        m = np.zeros((len(obs), N_ACTIONS), bool)
        m[:, 0] = True
        m[flat, 1] = m[flat, 2] = True
        m[~flat, 3] = True
        return m

    def act(self, obs: np.ndarray, mask: np.ndarray, eps: float, hold_bias: float = 0.9) -> np.ndarray:
        """obs [k, D], mask [k, 4]. Tadqiqotda KUTISH ehtimoli hold_bias (aks holda har sham savdo ochiladi va faqat xarajat to'planadi)."""
        q = self.q_values(obs)
        q = np.where(mask, q, -1e9)
        a = q.argmax(1)
        explore = self.rng.random(len(obs)) < eps
        for i in np.flatnonzero(explore):
            ok = np.flatnonzero(mask[i])
            if mask[i][1] or mask[i][2]:                         # pozitsiyasiz
                a[i] = 0 if self.rng.random() < hold_bias else self.rng.choice(ok[ok > 0])
            else:                                                 # pozitsiyada: asosan ushlab turadi
                a[i] = 0 if self.rng.random() < 0.97 else 3
        return a

    # ------------------------------------------------------------ o'rganish
    def learn(self, rb: Replay, bs: int, n_feat: int, share_elite: float = 0.1, share_mistake: float = 0.1,
              tau: float = 0.005) -> float:
        idx, w = rb.sample(bs, self.rng, share_elite, share_mistake)
        o, a, r, o2, d = rb.o[idx], rb.a[idx], rb.r[idx], rb.o2[idx], rb.d[idx]
        m2 = self.mask_from_obs(o2, n_feat)
        q2_online = np.where(m2, self.q.forward(o2), -1e9)
        a2 = q2_online.argmax(1)
        q2 = self.target.forward(o2)[np.arange(len(idx)), a2]
        y = r + self.gamma * (1.0 - d) * q2
        out, hs = self.q.forward(o, cache=True)
        pred = out[np.arange(len(idx)), a]
        td = y - pred
        huber = np.clip(td, -1.0, 1.0)
        dout = np.zeros_like(out)
        dout[np.arange(len(idx)), a] = -huber * w / len(idx)
        self.q.backward_adam(hs, dout, self.lr)
        rb.pr[idx] = np.abs(td) + 1e-3
        self.target.copy_from(self.q, tau)
        self.updates += 1
        self.last_loss = float(np.mean(huber ** 2 * w))
        return self.last_loss

    # ------------------------------------------------------------ saqlash
    def save(self, path: str, extra: Optional[Dict[str, Any]] = None) -> None:
        d = {("q_" + k): v for k, v in self.q.state().items()}
        d["sizes"] = np.array(self.sizes)
        d["updates"] = np.array(self.updates)
        if extra:
            import json
            d["meta"] = np.array(json.dumps(extra))
        np.savez_compressed(path, **d)

    @classmethod
    def load(cls, path: str) -> "Agent":
        z = np.load(path, allow_pickle=False)
        sizes = tuple(int(x) for x in z["sizes"])
        ag = cls(hidden=sizes[1:-1], obs_dim=sizes[0])
        ag.q.load_state({k[2:]: z[k] for k in z.files if k.startswith("q_")})
        ag.target.copy_from(ag.q)
        ag.updates = int(z["updates"])
        return ag

    @staticmethod
    def load_meta(path: str) -> Dict[str, Any]:
        import json
        z = np.load(path, allow_pickle=False)
        return json.loads(str(z["meta"])) if "meta" in z.files else {}
