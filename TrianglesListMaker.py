"""
TrianglesListMaker
===================

Scan all StaticMesh assets in the project and list those whose LOD0 triangle count
exceeds a configured threshold AND whose LOD0 reduction setting is still effectively
"full" (PercentTriangles ~ 1.0 / 100%). This identifies meshes that have not yet
been processed by scripts like `percenttriangles.py` which reduce LOD0.

Tested / written for Unreal Engine 5.6 Python API (should work on most 5.x versions).

Behavior:
  * Iterates all StaticMesh assets under /Game (can adjust SEARCH_PATHS).
  * Retrieves LOD0 triangle count (using get_num_triangles if available).
  * Retrieves LOD0 reduction_settings.percent_triangles (raw 0..1 float).
  * Considers a mesh "unreduced" if percent_triangles >= UNREDUCED_MIN_RAW (default 0.99).
  * Reports meshes with triangles >= TRIANGLE_THRESHOLD AND unreduced.
  * Optional CSV export; always logs a human-readable table.

Usage inside Unreal (Python):
  import TrianglesListMaker as tlm
  tlm.run()

Command line (UnrealEditor-Cmd.exe):
  UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript -script="TrianglesListMaker.py --execute"

Optional args (when __main__ executed):
  --csv              Write CSV to Saved/TrianglesReport.csv (or custom path with --csv=AbsOrRelPath)
  --threshold=60000  Override triangle threshold
  --minraw=0.995     Override unreduced min raw percent
  --limit=100        Only show first N matches (still counts full set in summary)

Note: This script does not modify assets.
"""

from __future__ import annotations
import unreal
from dataclasses import dataclass
from typing import List, Iterable, Optional
import os

# ---------------- Configuration ---------------- #

TRIANGLE_THRESHOLD = 50000          # LOD0 triangle count required to report
UNREDUCED_MIN_RAW = 0.99             # raw percent_triangles >= this value considered unreduced (UI ~99%)
SEARCH_PATHS = ["/Game"]              # Content root paths to search
CLASS_NAMES = ["StaticMesh"]
RECURSIVE_PATHS = True
RECURSIVE_CLASSES = True
CSV_DEFAULT_RELATIVE = os.path.join("Saved", "TrianglesReport.csv")  # relative to project root if used
OPEN_TOP_DEFAULT = 50  # default number of top meshes to auto-open for editing (set None or 0 to disable)

# Logging formatting
COLS = [
	("Triangles", 10),
	("PercentRaw", 10),
	("PercentUI", 9),
	("Nanite", 6),
	("AssetName", 40),
	("PackagePath", 60),
]

EPS_RAW = 0.0005  # tolerance for floating comparisons


def _log(msg: str):
	unreal.log(f"[TrianglesListMaker] {msg}")


@dataclass
class MeshInfo:
	name: str
	package_path: str
	triangle_count: int
	percent_raw: float
	nanite_enabled: bool
	asset: unreal.StaticMesh  # direct reference to asset for opening

	@property
	def percent_ui(self) -> float:
		return self.percent_raw * 100.0

	def to_row(self):
		return [
			str(self.triangle_count),
			f"{self.percent_raw:.4f}",
			f"{self.percent_ui:.2f}",
			("EN" if self.nanite_enabled else "DIS"),
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
	# Similar heuristics as percenttriangles.py
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
		# access render data? Might not exist in all contexts.
		render_data = static_mesh.get_editor_property('render_data') if hasattr(static_mesh, 'get_editor_property') else None
		if render_data and hasattr(render_data, 'lods'):
			lods = getattr(render_data, 'lods', [])
			if lods:
				# attempt to call get_num_triangles() if provided
				lod0 = lods[0]
				if hasattr(lod0, 'get_num_triangles'):
					return int(lod0.get_num_triangles())
	except Exception:
		pass
	return -1  # unknown


def is_unreduced(percent_raw: Optional[float], min_raw: float) -> bool:
	if percent_raw is None:
		return False
	return percent_raw + EPS_RAW >= min_raw


def collect_candidates(tri_threshold: int, unreduced_min_raw: float) -> List[MeshInfo]:
	results: List[MeshInfo] = []
	for sm in iter_static_meshes():
		name = sm.get_name()
		tri_count = get_lod0_triangle_count(sm)
		pct_raw = get_percent_triangles_lod0(sm)
		try:
			nanite_state = bool(sm.is_nanite_enabled())
		except Exception:
			# fallback older property path
			nanite_state = False
			try:
				nanite_settings = sm.get_editor_property('nanite_settings')
				if nanite_settings:
					nanite_state = bool(getattr(nanite_settings, 'enabled', False))
			except Exception:
				pass
		# Skip if tri count unknown or below threshold
		if tri_count < 0 or tri_count < tri_threshold:
			continue
		if is_unreduced(pct_raw, unreduced_min_raw):
			results.append(MeshInfo(
				name=name,
				package_path=sm.get_path_name(),
				triangle_count=tri_count,
				percent_raw=pct_raw if pct_raw is not None else 1.0,
				nanite_enabled=nanite_state,
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
		writer.writerow(["TriangleCount", "PercentRaw", "PercentUI", "Nanite", "AssetName", "PackagePath"])
		for m in meshes:
			writer.writerow([
				m.triangle_count,
				f"{m.percent_raw:.6f}",
				f"{m.percent_ui:.2f}",
				'EN' if m.nanite_enabled else 'DIS',
				m.name,
				m.package_path,
			])


def _open_assets(meshes: List[MeshInfo], count: int):
	if count <= 0:
		return
	if not meshes:
		return
	to_open = meshes[: min(count, len(meshes))]
	assets = [m.asset for m in to_open]
	try:
		editor_sub = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
		# Use bulk open if available
		if hasattr(editor_sub, 'open_editor_for_assets'):
			editor_sub.open_editor_for_assets(assets)
		else:
			for a in assets:
				editor_sub.open_editor_for_asset(a)
		_log(f"Opened {len(assets)} assets (top {count} by triangle count)")
	except Exception as e:
		_log(f"Failed opening assets: {e}")


def run(tri_threshold: int = TRIANGLE_THRESHOLD, unreduced_min_raw: float = UNREDUCED_MIN_RAW, csv: Optional[str] = None, limit: Optional[int] = None, open_top: Optional[int] = OPEN_TOP_DEFAULT):
	_log(f"Scanning StaticMesh assets (threshold={tri_threshold} unreduced_min_raw={unreduced_min_raw} open_top={open_top})")
	meshes = collect_candidates(tri_threshold, unreduced_min_raw)
	meshes.sort(key=lambda m: m.triangle_count, reverse=True)
	_log(f"Found {len(meshes)} unreduced meshes >= {tri_threshold} triangles")
	display = meshes if limit is None else meshes[:limit]
	rows = [m.to_row() for m in display]
	table = format_table(rows)
	for line in table.splitlines():
		unreal.log(line)
	if limit is not None and len(meshes) > limit:
		_log(f"(Showing first {limit} of {len(meshes)}; use --limit=<n> to change or omit to show all)")
	if csv:
		# Resolve relative path based on current working directory (usually project root when launched via editor)
		csv_path = os.path.abspath(csv)
		try:
			write_csv(meshes, csv_path)
			_log(f"CSV written: {csv_path}")
		except Exception as e:
			_log(f"Failed to write CSV '{csv_path}': {e}")
	if open_top is not None and open_top > 0:
		_open_assets(meshes, open_top)
	_log("Done.")
	return meshes


def _parse_args(argv):
	import argparse
	parser = argparse.ArgumentParser(description="List high-triangle unreduced StaticMeshes")
	parser.add_argument('--threshold', type=int, default=TRIANGLE_THRESHOLD, help='Triangle threshold (LOD0)')
	parser.add_argument('--minraw', type=float, default=UNREDUCED_MIN_RAW, help='Minimum raw percent_triangles to consider unreduced (0..1)')
	parser.add_argument('--csv', nargs='?', const=CSV_DEFAULT_RELATIVE, default=None, help='Write CSV (optional path)')
	parser.add_argument('--limit', type=int, default=None, help='Limit number of displayed rows')
	parser.add_argument('--open', type=int, default=OPEN_TOP_DEFAULT, help='Open top N meshes in the Static Mesh Editor (0 to disable)')
	return parser.parse_args(argv)


if __name__ == "__main__":
	import sys
	args = _parse_args(sys.argv[1:])
	run(tri_threshold=args.threshold, unreduced_min_raw=args.minraw, csv=args.csv, limit=args.limit, open_top=args.open)
