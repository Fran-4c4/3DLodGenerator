"""Portable declaration of a full local audit dataset."""
from lodext import strings
from dataclasses import dataclass, fields
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import ClassVar


@dataclass(frozen=True)
class DatasetSpec:
    """External dataset.json v1 contract; all fields required, no defaults.

    dataset_version: literal '1'; incompatible schema changes require a version.
    dataset_id: nonempty text, stable identity for run provenance.
    working_epsg: positive integer, checked as projected metres by the sampler;
      it belongs to this dataset, never a worldwide CRS default.
    halo_m: positive finite metres; available context declaration, which must
      cover the configured ground radius. It is not a claim of point coverage.
    footprints/source_inventory: relative local file paths. Geometry and all
      source entities are separate so missing geometry remains accountable.
    lidar_directory/dtm_file: relative local directory/file paths. '..' may
      reference shared resources within a copied project data tree. Copy all
      referenced assets when transferring the dataset. URLs/absolute paths and
      implicit environment expansion are rejected; no network is used.

    Changing a path changes sources; changing the CRS/halo changes sampling.
    Unknown/missing keys or invalid fields are rejected, not guessed or clamped.
    Source inventories can expose malformed relationships for audit; this is
    not a certificate that every row conforms to the production input contract.
    """

    RESOURCE_FIELDS: ClassVar[tuple[str, ...]] = (  # Validated resource-path group, not serialized state.
        strings.GeospatialInputFields.FOOTPRINTS, strings.GeospatialInputFields.SOURCE_INVENTORY,
        strings.GeospatialInputFields.LIDAR_DIRECTORY, strings.GeospatialInputFields.DTM_FILE,
    )  # Class-only resource group used by validation/resolution; never an input field.

    dataset_version: str  # Required audit declaration version; only '1' is accepted.
    dataset_id: str  # Nonempty stable identity recorded in trial provenance.
    working_epsg: int  # Explicit positive EPSG for this dataset's metric working CRS.
    halo_m: float  # Positive context radius in metres; must cover the trial ground search.
    footprints: str  # Relative local footprint GPKG file path; no URL/environment expansion.
    source_inventory: str  # Relative identity inventory file; accounts for absent source geometry.
    lidar_directory: str  # Relative cloud directory; resolved and verified by paths().
    dtm_file: str  # Relative ground-raster file; no automatic download or datum conversion.

    def __post_init__(self):
        """Reject unsupported versions, invalid halo/CRS and nonportable paths."""
        if self.dataset_version != strings.InputContractVersion.DATASET_VERSION or not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("Unsupported dataset version or empty dataset ID")
        if isinstance(self.working_epsg, bool) or not isinstance(self.working_epsg, int) or self.working_epsg <= 0:
            raise ValueError("working_epsg must be an explicit positive integer")
        if isinstance(self.halo_m, bool) or not isinstance(self.halo_m, (int, float)) or not math.isfinite(self.halo_m) or self.halo_m <= 0:
            raise ValueError("halo_m must be positive finite metres")
        for name in self.RESOURCE_FIELDS:
            value = getattr(self, name)
            if (not isinstance(value, str) or not value.strip() or "://" in value
                    or Path(value).is_absolute() or PurePosixPath(value).is_absolute()
                    or PureWindowsPath(value).drive or PureWindowsPath(value).root
                    or "$" in value or "%" in value or value.startswith("~")):
                raise ValueError(f"{name} must be a literal relative local path")

    @classmethod
    def read(cls, directory):
        """Read dataset.json with exactly the required versioned declaration keys.

        Validate values through DatasetSpec; file existence is checked by paths,
        not by this JSON reception step. No environment variables are expanded.
        """
        content = json.loads((Path(directory) / "dataset.json").read_text(encoding=strings.TextFileEncoding.UTF8))
        if not isinstance(content, dict) or set(content) != {field.name for field in fields(cls)}:
            raise ValueError("Dataset declaration must contain exactly the required keys")
        return cls(**content)

    def paths(self, directory):
        """Resolve declared resources from directory and verify file/directory kinds.

        Return absolute Paths keyed by resource field. Deliberate '..' references
        are allowed by this audit contract; copy the referenced shared resources
        with the fixture. This function neither creates nor modifies any files.
        """
        root = Path(directory).resolve()
        result = {name: (root / getattr(self, name)).resolve()
                  for name in self.RESOURCE_FIELDS}
        for name, path in result.items():
            if not (path.is_dir() if name == strings.GeospatialInputFields.LIDAR_DIRECTORY else path.is_file()):
                raise ValueError(f"Missing local dataset resource: {name}")
        return result
