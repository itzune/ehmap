# Licence of the files in `dist/elevation/`

These files are **not** under CC BY 4.0. They are derived from the Copernicus DEM GLO-30
(Copernicus WorldDEM-30) and are distributed under the
[Licence for the use of the Copernicus WorldDEM-30](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf),
which allows reproduction, distribution and modification free of charge, under these conditions.

Files: `copernicus_dem_25m.tif`, `copernicus_dem_50m.tif` (release assets),
`elevation_by_municipality.csv`, `elevation_by_territory.csv`.

Required notice for these modified data:

> produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space
> GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved

The organisations in charge of the Copernicus programme by law or by delegation do not incur
any liability for any use of the Copernicus WorldDEM-30.

This project is not endorsed by the Copernicus programme or any of the organisations in charge
of it. If you redistribute these files, modified or not, you must keep these notices and pass
the same obligations on to your users (Article 6 of the licence).

Changes made: the 1° tiles were mosaicked, reprojected from EPSG:4326 to ETRS89 / UTM 30N
(EPSG:25830) with bilinear resampling at 25 m, clipped to Euskal Herria and rounded to 0.1 m;
the 50 m version averages 2 × 2 cells and rounds to whole metres. The Copernicus DEM is a
surface model (DSM): it includes buildings and trees.
