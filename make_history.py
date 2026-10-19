"""M1 (yoki istalgan) tarix faylini M15 CSV ga aylantiradi:  python make_history.py kirish.pkl|csv chiqish.csv [M15]"""
import sys
import sl_core as sc

src, dst = sys.argv[1], sys.argv[2]
tf = sys.argv[3].upper() if len(sys.argv) > 3 else "M15"
df = sc.to_tf(sc.read_history_file(src, float(sys.argv[4]) if len(sys.argv) > 4 else 0.0), sc.TF_MIN[tf])
df.to_csv(dst, index_label="time")
print(len(df), "sham,", df.index[0], "..", df.index[-1], "->", dst)
