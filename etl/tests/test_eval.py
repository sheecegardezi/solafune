import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
eval = __import__("5_eval")
metrics = eval.metrics

def test_metrics_perfect():
    p = np.zeros((4, 4), np.uint8); p[1:3, 1:3] = 1
    m = metrics(p, p.copy(), np.zeros((4, 4), np.uint8))
    assert m["f1"] == 1.0 and m["iou"] == 1.0 and m["pred_ha"] == 0.04  # 4 px × 0.01 ha

def test_metrics_ignore_excluded():
    c = np.zeros((4, 4), np.uint8); c[0, 0] = 1
    m = metrics(c, c, np.ones((4, 4), np.uint8))   # everything ignored
    assert m["f1"] == 0.0 and m["pred_ha"] == 0.01  # 1 px × 0.01 ha; scoring excludes ignored px
