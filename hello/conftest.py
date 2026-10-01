# Empty conftest.py — pytest walks up looking for one, and its presence at this
# level makes pytest set rootdir here so `from main import app` in tests/ works
# without any explicit sys.path manipulation.
