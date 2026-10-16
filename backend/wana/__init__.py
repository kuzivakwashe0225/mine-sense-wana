import os

# rasterio and pyproj ship their own PROJ/GDAL data. A system-wide PROJ_LIB or GDAL_DATA from another
# install (PostGIS, QGIS, OSGeo4W) points them at an incompatible proj.db and every CRS lookup fails.
# Set WANA_KEEP_PROJ_ENV=1 to keep the system values.
if not os.environ.get("WANA_KEEP_PROJ_ENV"):
    for _k in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
        os.environ.pop(_k, None)
