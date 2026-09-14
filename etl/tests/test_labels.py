import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import geopandas as gpd
from shapely.geometry import box
make_training_data = __import__("2_make_training_data")
label_windows = make_training_data.label_windows

def _gdf(years_xs):
    return gpd.GeoDataFrame(
        {"year": [y for y, _ in years_xs]},
        geometry=[box(x, -10.60, x + 0.001, -10.599) for _, x in years_xs],
        crs="EPSG:4326",
    )

def test_label_windows_rule():
    gdf = _gdf([(2019, -62.0), (2020, -62.1), (2021, -62.2), (2022, -62.3), (2025, -62.4)])
    change, ignore = label_windows(gdf, 2021, 2024)
    assert sorted(change.year.tolist()) == [2022]        # t1 < year <= t2
    assert sorted(ignore.year.tolist()) == [2021, 2025]  # t1 ambiguous; >t2 invisible
