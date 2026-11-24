# Local data

This directory can hold unversioned inputs:

```text
data/
├── footprints/   # GeoPackage
├── lidar/        # LAS, LAZ or COPC
└── terrain/      # GeoTIFF DTM
```

Declare paths in the local configuration. Retain originals/provenance and place
reprojections, conversions and crops in a run's work directory. Outputs belong
under ignored `outputs/`. Small original synthetic examples may be versioned
under `examples/` or test fixtures with their descriptions and permissions.
