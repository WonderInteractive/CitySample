"""
OverReducedFinder
=================

Find and FIX StaticMesh assets that have been over-reduced during optimization:
- LOD0 reduction percent < REDUCTION_THRESHOLD (default 9%)
- LOD0 triangle count < TRIANGLE_THRESHOLD (default 500)
- Package path contains BUILDING_TOKEN (default "Building")

This automatically restores over-reduced building meshes back to 100% LOD0 quality.
Since they're already under 500 triangles at ~9%, setting them to 100% won't 
make them unreasonably large.

Tested / written for Unreal Engine 5.6 Python API (should work on most 5.x versions).

Behavior:
  * Scans all StaticMesh assets under /Game (configurable via SEARCH_PATHS).
  * Filters by package path containing building token.
  * Checks LOD0 reduction_settings.percent_triangles (raw 0..1 float).
  * Checks LOD0 triangle count using get_num_triangles.
  * Automatically sets LOD0 reduction to 100% for qualifying meshes.
  * Rebuilds LODs and saves modified assets.
  * Optional dry-run mode to preview changes without applying.

Usage inside Unreal (Python):
  import OverReducedFinder as orf
  orf.run()                # apply fixes (default)
  orf.run(dry_run=True)    # preview changes

Command line (UnrealEditor-Cmd.exe):
  UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript -script="OverReducedFinder.py --apply"

Optional args (when __main__ executed):
  --dry-run               Preview changes without applying
  --apply                 Actually apply the fixes (default when run from Python)
  --csv                   Write CSV to Saved/OverReducedReport.csv
  --reduction=8.0         Override reduction threshold (UI percent)
  --triangles=400         Override triangle threshold
  --token=Building        Override building path token
  --limit=100            Only show first N matches in table

Note: This script MODIFIES assets by setting LOD0 reduction to 100%.
"""

from __future__ import annotations
import unreal
from dataclasses import dataclass
from typing import List, Iterable, Optional
import os

# ---------------- Configuration ---------------- #

REDUCTION_THRESHOLD_UI = 9.0         # UI percent below which mesh is considered over-reduced
TRIANGLE_THRESHOLD = 500             # LOD0 triangle count below which mesh is considered too sparse
BUILDING_TOKEN = "Building"          # substring required in package path
SEARCH_PATHS = ["/Game"]             # Content root paths to search
CLASS_NAMES = ["StaticMesh"]
RECURSIVE_PATHS = True
RECURSIVE_CLASSES = True
CSV_DEFAULT_RELATIVE = os.path.join("Saved", "OverReducedReport.csv")
TARGET_PERCENT_RAW = 1.0             # restore to 100% (raw 1.0)
TARGET_PERCENT_UI = 100.0            # restore to 100% (UI display)

# Logging formatting
COLS = [
    ("Action", 8),
    ("TrisBefore", 10),
    ("PercentBefore", 12),
    ("PercentAfter", 11),
    ("AssetName", 40),
    ("PackagePath", 50),
]

# Derived values
REDUCTION_THRESHOLD_RAW = REDUCTION_THRESHOLD_UI / 100.0
EPS_RAW = 0.0005  # tolerance for floating comparisons


def _log(msg: str):
    unreal.log(f"[OverReducedFinder] {msg}")


@dataclass
class MeshInfo:
    name: str
    package_path: str
    triangle_count: int
    percent_raw_before: float
    asset: unreal.StaticMesh  # direct reference to asset for modification
    action: str = "FOUND"  # FOUND, FIXED, FAILED, SKIPPED
    percent_raw_after: Optional[float] = None

    @property
    def percent_ui_before(self) -> float:
        return self.percent_raw_before * 100.0
        
    @property
    def percent_ui_after(self) -> float:
        return self.percent_raw_after * 100.0 if self.percent_raw_after is not None else 0.0

    def to_row(self):
        return [
            self.action,
            str(self.triangle_count),
            f"{self.percent_ui_before:.1f}%",
            f"{self.percent_ui_after:.1f}%" if self.percent_raw_after is not None else "--",
            self.name,
            self.package_path,
        ]


# --------------- Core Unreal Helpers --------------- #

def _get_asset_registry():
    return unreal.AssetRegistryHelpers.get_asset_registry()


def iter_static_meshes() -> Iterable[unreal.StaticMesh]:
    registry = _get_asset_registry()
    ar_filter = unreal.ARFilter(
        class_names=CLASS_NAMES,
        recursive_paths=RECURSIVE_PATHS,
        recursive_classes=RECURSIVE_CLASSES,
        package_paths=SEARCH_PATHS,
        include_only_on_disk_assets=False,
    )
    assets = registry.get_assets(ar_filter)
    for a in assets:
        try:
            sm = a.get_asset()
            if isinstance(sm, unreal.StaticMesh):
                yield sm
        except Exception:
            continue


def get_percent_triangles_lod0(static_mesh: unreal.StaticMesh) -> Optional[float]:
    # Same fallback strategy as other scripts
    try:
        lods = static_mesh.get_editor_property("lods")
        if lods:
            red = lods[0].get_editor_property("reduction_settings")
            return float(red.percent_triangles)
    except Exception:
        pass
    try:
        source_models = static_mesh.get_editor_property("source_models")
        if source_models:
            red = source_models[0].get_editor_property("reduction_settings")
            return float(red.percent_triangles)
    except Exception:
        pass
    try:
        smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        settings = smes.get_lod_reduction_settings(static_mesh, 0)
        if settings:
            return float(settings.percent_triangles)
    except Exception:
        pass
    return None


def get_lod0_triangle_count(static_mesh: unreal.StaticMesh) -> int:
    try:
        if hasattr(static_mesh, 'get_num_triangles'):
            return int(static_mesh.get_num_triangles(0))
    except Exception:
        pass
    # Fallback attempt via editor data (less reliable)
    try:
        render_data = static_mesh.get_editor_property('render_data') if hasattr(static_mesh, 'get_editor_property') else None
        if render_data and hasattr(render_data, 'lods'):
            lods = getattr(render_data, 'lods', [])
            if lods:
                lod0 = lods[0]
                if hasattr(lod0, 'get_num_triangles'):
                    return int(lod0.get_num_triangles())
    except Exception:
        pass
    return -1  # unknown


def set_percent_triangles_lod0(static_mesh: unreal.StaticMesh, value_raw: float) -> bool:
    """Set LOD0 reduction percent triangles. Returns True if successful."""
    # Same fallback strategy as percenttriangles.py
    # 1) Direct LOD path
    try:
        lods = static_mesh.get_editor_property("lods")
        if lods:
            lod0 = lods[0]
            red = lod0.get_editor_property("reduction_settings")
            red.set_editor_property("percent_triangles", value_raw)
            lod0.set_editor_property("reduction_settings", red)
            static_mesh.set_editor_property("lods", lods)
            return True
    except Exception:
        pass
    # 2) source_models path
    try:
        source_models = static_mesh.get_editor_property("source_models")
        if source_models:
            red = source_models[0].get_editor_property("reduction_settings")
            red.set_editor_property("percent_triangles", value_raw)
            source_models[0].set_editor_property("reduction_settings", red)
            static_mesh.set_editor_property("source_models", source_models)
            return True
    except Exception:
        pass
    # 3) StaticMeshEditorSubsystem API
    try:
        smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        settings = smes.get_lod_reduction_settings(static_mesh, 0)
        if settings:
            settings.set_editor_property("percent_triangles", value_raw)
            smes.set_lod_reduction_settings(static_mesh, 0, settings)
            return True
    except Exception:
        pass
    return False


def build_and_save(static_mesh: unreal.StaticMesh) -> bool:
    """Rebuild LODs and save asset. Returns True if successful."""
    smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    build_ok = False
    # Try different build APIs
    try:
        if hasattr(smes, 'rebuild_lods'):
            smes.rebuild_lods(static_mesh)
            build_ok = True
    except Exception:
        pass
    if not build_ok:
        try:
            if hasattr(smes, 'build_static_mesh'):
                smes.build_static_mesh(static_mesh)
                build_ok = True
        except Exception:
            pass
    if not build_ok:
        try:
            if hasattr(static_mesh, 'build'):
                static_mesh.build()
                build_ok = True
        except Exception:
            pass
    
    # Save asset
    save_ok = False
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(static_mesh)
        save_ok = True
    except Exception:
        pass
    if not save_ok:
        try:
            package = static_mesh.get_outer()
            if hasattr(unreal, 'EditorLoadingAndSavingUtils'):
                unreal.EditorLoadingAndSavingUtils.save_packages([package], only_dirty=True)
                save_ok = True
        except Exception:
            pass
    
    return build_ok and save_ok


def is_over_reduced(percent_raw: Optional[float], reduction_threshold_raw: float) -> bool:
    if percent_raw is None:
        return False
    return percent_raw < reduction_threshold_raw


def has_building_token(package_path: str, token: str) -> bool:
    return token.lower() in package_path.lower()


def collect_candidates(reduction_threshold_raw: float, tri_threshold: int, building_token: str) -> List[MeshInfo]:
    results: List[MeshInfo] = []
    for sm in iter_static_meshes():
        name = sm.get_name()
        package_path = sm.get_path_name()
        
        # Filter by building token first (quick check)
        if not has_building_token(package_path, building_token):
            continue
            
        tri_count = get_lod0_triangle_count(sm)
        pct_raw = get_percent_triangles_lod0(sm)
        
        # Skip if tri count unknown
        if tri_count < 0:
            continue
            
        # Check all conditions: over-reduced AND low triangle count
        if (is_over_reduced(pct_raw, reduction_threshold_raw) and 
            tri_count < tri_threshold):
            results.append(MeshInfo(
                name=name,
                package_path=package_path,
                triangle_count=tri_count,
                percent_raw_before=pct_raw if pct_raw is not None else 0.0,
                asset=sm,
            ))
    return results


def format_table(rows: List[List[str]]) -> str:
    # dynamic width: use configured width but allow bigger if content longer
    col_widths = []
    for idx, (header, default_w) in enumerate(COLS):
        max_content = max([len(r[idx]) for r in rows] + [len(header)]) if rows else len(header)
        col_widths.append(max(default_w, max_content))
    header_line = ' '.join(h.ljust(col_widths[i]) for i, (h, _) in enumerate(COLS))
    sep_line = ' '.join('-' * col_widths[i] for i in range(len(COLS)))
    body_lines = [' '.join(r[i].ljust(col_widths[i]) for i in range(len(COLS))) for r in rows]
    return '\n'.join([header_line, sep_line] + body_lines)


def write_csv(meshes: List[MeshInfo], csv_path: str):
    import csv
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Action", "TriangleCount", "PercentBefore", "PercentAfter", "AssetName", "PackagePath"])
        for m in meshes:
            writer.writerow([
                m.action,
                m.triangle_count,
                f"{m.percent_ui_before:.2f}%",
                f"{m.percent_ui_after:.2f}%" if m.percent_raw_after is not None else "--",
                m.name,
                m.package_path,
            ])


def process_mesh(mesh_info: MeshInfo, dry_run: bool = True) -> bool:
    """Process a single mesh. Returns True if successful."""
    if dry_run:
        mesh_info.action = "DRY-RUN"
        mesh_info.percent_raw_after = TARGET_PERCENT_RAW
        return True
    
    # Actually apply the fix
    if set_percent_triangles_lod0(mesh_info.asset, TARGET_PERCENT_RAW):
        if build_and_save(mesh_info.asset):
            mesh_info.action = "FIXED"
            mesh_info.percent_raw_after = TARGET_PERCENT_RAW
            return True
        else:
            mesh_info.action = "SAVE-FAIL"
            return False
    else:
        mesh_info.action = "SET-FAIL"
        return False


def run(reduction_threshold_ui: float = REDUCTION_THRESHOLD_UI, 
        tri_threshold: int = TRIANGLE_THRESHOLD, 
        building_token: str = BUILDING_TOKEN,
        csv: Optional[str] = None, 
        limit: Optional[int] = None, 
        dry_run: bool = False):
    
    reduction_threshold_raw = reduction_threshold_ui / 100.0
    mode = "DRY-RUN" if dry_run else "APPLYING FIXES"
    _log(f"Scanning for over-reduced building meshes ({mode}) (reduction<{reduction_threshold_ui}% triangles<{tri_threshold} token='{building_token}')")
    
    meshes = collect_candidates(reduction_threshold_raw, tri_threshold, building_token)
    # Sort by triangle count ascending (lowest triangle count first - most problematic)
    meshes.sort(key=lambda m: m.triangle_count)
    
    _log(f"Found {len(meshes)} over-reduced building meshes")
    
    if not meshes:
        _log("No over-reduced meshes found!")
        return meshes
    
    # Process each mesh
    fixed = 0
    failed = 0
    for mesh in meshes:
        if process_mesh(mesh, dry_run):
            fixed += 1
        else:
            failed += 1
    
    display = meshes if limit is None else meshes[:limit]
    rows = [m.to_row() for m in display]
    table = format_table(rows)
    for line in table.splitlines():
        unreal.log(line)
    
    if limit is not None and len(meshes) > limit:
        _log(f"(Showing first {limit} of {len(meshes)}; use --limit=<n> to change or omit to show all)")
    
    _log(f"Results: {fixed} successful, {failed} failed")
    if dry_run:
        _log("DRY RUN - no changes applied. Use dry_run=False or --apply to actually fix meshes.")
    
    if csv:
        csv_path = os.path.abspath(csv)
        try:
            write_csv(meshes, csv_path)
            _log(f"CSV written: {csv_path}")
        except Exception as e:
            _log(f"Failed to write CSV '{csv_path}': {e}")
    
    _log("Done.")
    return meshes


def _parse_args(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Find and fix over-reduced building StaticMeshes")
    parser.add_argument('--reduction', type=float, default=REDUCTION_THRESHOLD_UI, help='Reduction threshold UI percent (meshes below this are over-reduced)')
    parser.add_argument('--triangles', type=int, default=TRIANGLE_THRESHOLD, help='Triangle threshold (meshes below this are too sparse)')
    parser.add_argument('--token', type=str, default=BUILDING_TOKEN, help='Building token required in package path')
    parser.add_argument('--csv', nargs='?', const=CSV_DEFAULT_RELATIVE, default=None, help='Write CSV (optional path)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of displayed rows')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--apply', action='store_true', default=True, help='Actually apply the fixes (default)')
    return parser.parse_args(argv)


if __name__ == "__main__":
    import sys
    args = _parse_args(sys.argv[1:])
    dry_run = args.dry_run  # --dry-run enables dry run mode
    run(reduction_threshold_ui=args.reduction, 
        tri_threshold=args.triangles, 
        building_token=args.token,
        csv=args.csv, 
        limit=args.limit, 
        dry_run=dry_run)