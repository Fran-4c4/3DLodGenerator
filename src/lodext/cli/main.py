"""Run `lodext --help` for the independent local workflow."""
from lodext import strings
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    """Dispatch the local CLI and return its documented process status.

    argv=None reads process arguments. Parse options without inventing algorithm
    defaults; validated configuration types own those. Return 0 for success,
    3 for reported partial reconstruction and 2 for execution errors with a
    bounded stderr diagnostic. Argument errors use argparse's SystemExit.
    Validation commands inspect structure/headers, not reconstruction accuracy.
    """
    parser = argparse.ArgumentParser(prog="lodext",description="Reconstruct auditable buildings and class-lifted surfaces from local geodata.")
    commands = parser.add_subparsers(dest=strings.CommandLineArguments.SUBCOMMAND_DESTINATION,required=True)
    build = commands.add_parser("build",help="Read config JSON and generate a new CityJSON run")
    build.add_argument(strings.CommandLineArguments.CONFIG_POSITIONAL,type=Path)
    build.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True,help="New run directory; existing paths rejected")
    check = commands.add_parser("validate",help="Validate the input contract without reconstruction")
    check.add_argument(strings.CommandLineArguments.CONFIG_POSITIONAL,type=Path)
    model = commands.add_parser("validate-cityjson",help="Check generated CityJSON structure, relationships and closed-shell edges")
    model.add_argument("model",type=Path)
    demo = commands.add_parser("demo",help="Create a portable synthetic GeoPackage + DTM + LAS and configuration")
    demo.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True)
    surface_build = commands.add_parser("build-surfaces",help="Lift Road/Terrain/Forest/Water; no scene stitching yet")
    surface_build.add_argument(strings.CommandLineArguments.CONFIG_POSITIONAL,type=Path)
    surface_build.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True)
    surface_check = commands.add_parser("validate-surfaces",help="Check the standalone surface polygon contract and LiDAR headers")
    surface_check.add_argument(strings.CommandLineArguments.CONFIG_POSITIONAL,type=Path)
    surface_demo = commands.add_parser("demo-surfaces",help="Create original four-class surface controls and the building regression")
    surface_demo.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True)
    tiles = commands.add_parser("tiles",help="Convert CityJSON to GLB + one static 3D Tiles 1.1 tile")
    tiles.add_argument("model",type=Path)
    tiles.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True)
    tiles.add_argument("--z-offset-m",type=float,required=True,help="Explicit metres added to source Z to declare ellipsoidal placement; no guessed datum conversion")
    args = parser.parse_args(argv)
    try:
        from lodext.io.native import configure_native_environment
        configure_native_environment()
        if args.command=="build-surfaces":
            from lodext.surface_pipeline import run_surfaces
            summary = run_surfaces(args.config,args.output,
                lambda phase,details: print(json.dumps({strings.ProgressEventFields.PHASE:phase,**details}),flush=True))
            return 3 if summary[strings.ReconstructionRunFields.STATUS]==strings.ReconstructionRunStatus.PARTIAL else 0
        if args.command=="validate-surfaces":
            from lodext.core.surfaces import SurfaceConfig
            from lodext.io.surfaces import read_surfaces
            from lodext.io.sampling import lidar_files
            import laspy
            config = SurfaceConfig.read(args.config)
            root = args.config.resolve().parent
            features,_ = read_surfaces(config,root)
            files = lidar_files(config.lidar,root)
            for path in files:
                with laspy.open(path) as reader:
                    if reader.header.parse_crs() is None:
                        raise ValueError("LiDAR source has no declared CRS")
            print(json.dumps({strings.InputReceptionSummaryFields.OBJECT_COUNT:len(features),strings.LidarInventoryFields.LIDAR_FILES:len(files),
                              strings.ValidationReportFields.SCOPE:"surface input structure and headers only; no stitching certification"}))
            return 0
        if args.command=="demo-surfaces":
            from lodext.surface_demo import create_surface_demo
            create_surface_demo(args.output)
            print("Created surfaces.json and original controls; run lodext build-surfaces <directory>/surfaces.json --output <new-directory>")
            return 0
        if args.command=="build":
            from lodext.pipeline import run_build
            def progress(phase,details):
                """Emit one flushed JSON event for the building CLI's progress."""
                print(json.dumps({strings.ProgressEventFields.PHASE:phase,**details},ensure_ascii=False),flush=True)
            summary = run_build(args.config,args.output,progress)
            return 3 if summary[strings.ReconstructionRunFields.STATUS]==strings.ReconstructionRunStatus.PARTIAL else 0
        if args.command=="validate":
            from lodext.core.config import BuildConfig
            from lodext.io.footprints import read_footprints
            config = BuildConfig.read(args.config)
            features,_ = read_footprints(config,args.config.resolve().parent)
            import rasterio
            import laspy
            from lodext.io.sampling import lidar_files
            root = args.config.resolve().parent
            if config.dtm is not None:
                with rasterio.open(root/config.dtm) as raster:
                    if raster.crs is None or raster.nodata is None or raster.count!=1:
                        raise ValueError("DTM requires CRS, explicit NoData and one elevation band")
            files = lidar_files(config.lidar,root)
            for path in files:
                with laspy.open(path) as reader:
                    if reader.header.parse_crs() is None:
                        raise ValueError("Declared LiDAR source has no CRS")
            print(json.dumps({strings.InputReceptionSummaryFields.OBJECT_COUNT:len(features),strings.InputReceptionSummaryFields.EXCLUDED_COUNT:sum(bool(f.issues) for f in features),strings.LidarInventoryFields.LIDAR_FILES:len(files),"dtm_header":"not_used" if config.dtm is None else "valid",strings.ValidationReportFields.SCOPE:"input structure and resource headers; no sampling or geometry certification"},ensure_ascii=False))
        elif args.command=="validate-cityjson":
            from lodext.export.cityjson import validate_cityjson
            print(json.dumps(validate_cityjson(json.loads(args.model.read_text(encoding=strings.TextFileEncoding.UTF8)))))
        elif args.command=="tiles":
            from lodext.export.tiles import TileConfig,write_tiles
            print(json.dumps(write_tiles(args.model,args.output,TileConfig(args.z_offset_m)),ensure_ascii=False))
        else:
            from lodext.demo import create_demo
            create_demo(args.output)
            print("Created synthetic inputs and configurations; run lodext build <directory>/build.lidar.json --output <new-directory>")
        return 0
    except Exception as exc:
        # Public boundary also covers native reader/PROJ/decoder exceptions.
        # Library callers retain original exceptions; the CLI returns its
        # documented error status with a bounded, visible diagnostic.
        print(f"lodext: {type(exc).__name__}: {str(exc)[:2000]}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
