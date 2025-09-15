"""
Batch reduce LOD0 percent triangles for Static Mesh assets whose name contains '_BLDG_'.

Tested / written for Unreal Engine 5.6 Python API.

Behavior:
	* Finds all StaticMesh assets in the project whose asset name contains the token _BLDG_.
	* Ensures Nanite is disabled on each candidate mesh.
	* Reads LOD0 ReductionSettings.PercentTriangles. Engine APIs sometimes store this as a RAW 0-1 float
		while the UI shows 0-100. This script normalizes to RAW internally and exposes configured values in UI terms.
	* If current value (raw) is ~1.0 (100%) it will be set to TARGET_PERCENT_UI (converted to raw) and LODs rebuilt.
	* Saves modified assets.

Safety:
  * Dry run option prints what WOULD change without saving.
  * Skips meshes already <= target percent.
  * Logs summary at end.

Usage (inside Unreal Editor Python console or via a script execution):

	import percenttriangles
	percenttriangles.run(dry_run=True)   # preview
	percenttriangles.run()               # apply changes

To run headless you can use the Editor-Cmd line:
  UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript -script="percenttriangles.py --execute"
Or create a commandlet wrapper (not included here).

Adjust TARGET_PERCENT_UI or NAME_TOKEN below as needed. Tolerances (EPS_UI/EPS_RAW) can be tuned if precision differs.
"""

from __future__ import annotations
import unreal
from typing import List, Tuple

# Configurable constants
NAME_TOKEN = "_veh"           # substring required in asset name

# The UI shows Percent Triangles as 0-100, but some APIs store it 0.0-1.0.
# Define target in UI percent for readability, then convert to raw.
TARGET_PERCENT_UI = 10.0          # Show in UI terms (10%)
ONLY_WHEN_EQUALS_UI = 100.0      # Only modify meshes currently at 100% (full resolution)

# Tolerances (avoid float precision mismatches)
EPS_UI = 0.01                    # 0.01% tolerance when comparing UI values
EPS_RAW = 0.001                 # Raw (0-1) tolerance

# Derived raw values
TARGET_PERCENT_RAW = TARGET_PERCENT_UI / 100.0
ONLY_WHEN_EQUALS_RAW = ONLY_WHEN_EQUALS_UI / 100.0

# Triangle count cutoff: only modify meshes whose LOD0 (or total reported) triangle count exceeds this.
TRIANGLE_CUTOFF = 0        # Set to 0 to disable cutoff
APPLY_IF_PERCENT_EQ_FULL = True   # Require current percent ~= 100% (raw 1.0) before changing
SKIP_IF_ALREADY_BELOW_TARGET = True  # Skip meshes already <= target percent

# Debug / introspection configuration defaults
INTROSPECT_MAX_DEPTH = 3          # recursion depth for debug dump
INTROSPECT_MAX_CHILDREN = 40      # limit per object to avoid log spam
INTROSPECT_INCLUDE_PRIVATE = False


def _log(msg: str):
	unreal.log(f"[percenttriangles] {msg}")


def find_static_meshes_with_token(token: str) -> List[unreal.StaticMesh]:
	registry = unreal.AssetRegistryHelpers.get_asset_registry()
	filter = unreal.ARFilter(
		class_names=["StaticMesh"],
		recursive_classes=True,
		recursive_paths=True,
		include_only_on_disk_assets=False,
		package_paths=["/Game"],  # limit to game content; adjust if needed
	)
	assets = registry.get_assets(filter)
	matches: List[unreal.StaticMesh] = []
	for a in assets:
		# asset_name is an FName (unreal.Name). Cast to str for substring test.
		name_str = str(a.asset_name)
		if token in name_str:
			sm = a.get_asset()
			if isinstance(sm, unreal.StaticMesh):
				matches.append(sm)
	return matches


def get_percent_triangles_lod0(static_mesh: unreal.StaticMesh) -> float | None:
	"""Return RAW (0-1) PercentTriangles for LOD0 reduction settings, or None if unavailable."""
	# In UE5, reduction settings are per LOD. Use get_editor_property
	# 1) Direct LOD struct property access
	try:
		lods = static_mesh.get_editor_property("lods")
		if lods:
			lod0 = lods[0]
			red = lod0.get_editor_property("reduction_settings")
			return float(red.percent_triangles)
	except Exception:
		pass
	# 2) source_models path
	try:
		source_models = static_mesh.get_editor_property("source_models")
		if source_models:
			red = source_models[0].get_editor_property("reduction_settings")
			return float(red.percent_triangles)
	except Exception:
		pass
	# 3) StaticMeshEditorSubsystem reduction settings (if available)
	try:
		smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
		settings = smes.get_lod_reduction_settings(static_mesh, 0)
		if settings:
			return float(settings.percent_triangles)
	except Exception:
		pass
	return None


def set_percent_triangles_lod0(static_mesh: unreal.StaticMesh, value_raw: float) -> bool:
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
	_log(f"Failed to set percent triangles on {static_mesh.get_name()}: no writable path")
	return False


def ensure_nanite_disabled(static_mesh: unreal.StaticMesh) -> tuple[bool, bool, bool]:
	"""Ensure Nanite is disabled.

	Returns:
		(was_enabled, is_enabled_after, changed)
	"""
	was_enabled = False
	changed = False
	is_enabled_after = False
	# Preferred API
	try:
		was_enabled = bool(static_mesh.is_nanite_enabled())
		if was_enabled:
			static_mesh.set_nanite_enabled(False)
			changed = True
		is_enabled_after = bool(static_mesh.is_nanite_enabled())
		return was_enabled, is_enabled_after, changed
	except AttributeError:
		pass

	# Fallback older property path
	try:
		nanite_settings = static_mesh.get_editor_property("nanite_settings")
		if nanite_settings:
			was_enabled = bool(getattr(nanite_settings, "enabled", False))
			if was_enabled:
				setattr(nanite_settings, "enabled", False)
				static_mesh.set_editor_property("nanite_settings", nanite_settings)
				changed = True
			is_enabled_after = bool(getattr(nanite_settings, "enabled", False))
		return was_enabled, is_enabled_after, changed
	except Exception:
		pass
	return was_enabled, is_enabled_after, changed


def build_and_save(static_mesh: unreal.StaticMesh):
	smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
	# Different engine versions expose different build APIs; try several.
	build_ok = False
	# 1) rebuild_lods (newer API in some branches)
	try:
		if hasattr(smes, 'rebuild_lods'):
			smes.rebuild_lods(static_mesh)
			build_ok = True
	except Exception as e:
		_log(f"Warning: rebuild_lods failed on {static_mesh.get_name()}: {e}")
	# 2) build static mesh (generic)
	if not build_ok:
		try:
			if hasattr(smes, 'build_static_mesh'):
				smes.build_static_mesh(static_mesh)
				build_ok = True
		except Exception as e:
			_log(f"Warning: build_static_mesh failed on {static_mesh.get_name()}: {e}")
	# 3) Fallback: call build from asset if available
	if not build_ok:
		try:
			if hasattr(static_mesh, 'build'):  # sometimes exists
				static_mesh.build()
				build_ok = True
		except Exception as e:
			_log(f"Warning: static_mesh.build() failed on {static_mesh.get_name()}: {e}")
	if not build_ok:
		_log(f"Warning: No LOD rebuild method succeeded for {static_mesh.get_name()} (may still save with new settings)")
	package = static_mesh.get_outer()  # UPackage
	# Save asset (API differences across versions)
	try:
		unreal.EditorAssetLibrary.save_loaded_asset(static_mesh)
	except Exception as e:
		_log(f"Warning: save_loaded_asset failed for {static_mesh.get_name()}: {e}")
	# Attempt broader package save via EditorLoadingAndSavingUtils if available
	try:
		if hasattr(unreal, 'EditorLoadingAndSavingUtils'):
			unreal.EditorLoadingAndSavingUtils.save_packages([package], only_dirty=True)
	except Exception as e:
		_log(f"Warning: save_packages fallback failed for {static_mesh.get_name()}: {e}")


def process_mesh(static_mesh: unreal.StaticMesh, dry_run: bool = True) -> Tuple[bool, str]:
	name = static_mesh.get_name()
	percent_raw = get_percent_triangles_lod0(static_mesh)
	if percent_raw is None:
		return False, f"{name}: Could not read LOD0 percent triangles"
	percent_ui = percent_raw * 100.0
	# Triangle count acquisition (LOD0). If fails, tri_count becomes -1 and we proceed (unless cutoff enabled).
	tri_count = -1
	try:
		# Most engine versions support get_num_triangles(lod_index)
		if hasattr(static_mesh, 'get_num_triangles'):
			tri_count = static_mesh.get_num_triangles(0)
	except Exception:
		pass
	was_nanite, is_nanite_after, nanite_changed = ensure_nanite_disabled(static_mesh)
	# Already at target (within tolerance)
	if SKIP_IF_ALREADY_BELOW_TARGET and abs(percent_raw - TARGET_PERCENT_RAW) <= EPS_RAW:
		return False, f"{name}: Already at target {TARGET_PERCENT_UI}% (raw {percent_raw:.6f})"
	# Triangle cutoff check
	if TRIANGLE_CUTOFF > 0 and tri_count >= 0 and tri_count <= TRIANGLE_CUTOFF:
		return False, f"{name}: Skipped (triangles {tri_count} <= cutoff {TRIANGLE_CUTOFF})"
	# Percent full-resolution requirement
	if APPLY_IF_PERCENT_EQ_FULL and abs(percent_raw - ONLY_WHEN_EQUALS_RAW) > EPS_RAW:
		return False, f"{name}: Skipped (percent {percent_ui:.4f}% raw {percent_raw:.6f} not ~{ONLY_WHEN_EQUALS_UI}%)"
	if dry_run:
		return True, (
			f"{name}: Would change {percent_ui:.4f}% -> {TARGET_PERCENT_UI}% (tris {tri_count}) "
			f"(raw {percent_raw:.6f}->{TARGET_PERCENT_RAW:.6f}) "
			f"nanite_before={'EN' if was_nanite else 'DIS'} nanite_after={'EN' if is_nanite_after else 'DIS'} changed={nanite_changed}"
		)

	if set_percent_triangles_lod0(static_mesh, TARGET_PERCENT_RAW):
		build_and_save(static_mesh)
		return True, (
			f"{name}: Changed {percent_ui:.4f}% -> {TARGET_PERCENT_UI}% (tris {tri_count}) "
			f"(raw {percent_raw:.6f}->{TARGET_PERCENT_RAW:.6f}) "
			f"nanite_before={'EN' if was_nanite else 'DIS'} nanite_after={'EN' if is_nanite_after else 'DIS'} changed={nanite_changed}"
		)
	else:
		return False, f"{name}: FAILED to apply change (had {percent_ui:.4f}% raw {percent_raw:.6f})"


def run(dry_run: bool = False, diagnose: bool = False, sample_count: int = 3):
	_log(f"Starting scan (dry_run={dry_run} diagnose={diagnose}) token='{NAME_TOKEN}' target={TARGET_PERCENT_UI}% (raw {TARGET_PERCENT_RAW}) when_equals={ONLY_WHEN_EQUALS_UI}%")
	meshes = find_static_meshes_with_token(NAME_TOKEN)
	_log(f"Found {len(meshes)} candidate meshes")
	if diagnose:
		# Print current percents for first few meshes regardless of readability failure
		for sm in meshes[:sample_count]:
			pct_raw = get_percent_triangles_lod0(sm)
			pct_ui = None if pct_raw is None else pct_raw * 100.0
			_log(f"DIAG {sm.get_name()} percent_triangles_raw={pct_raw} ui={pct_ui}")
		if meshes:
			_log("Running introspection on first mesh for diagnosis")
			debug_introspect_first_mesh()
	changed = 0
	skipped = 0
	errors = 0
	for sm in meshes:
		ok, message = process_mesh(sm, dry_run=dry_run)
		if ok:
			changed += 1
		else:
			if "Skipped" in message or "Already" in message:
				skipped += 1
			else:
				errors += 1
		unreal.log(message)
	_log(f"Done. changed={changed} skipped={skipped} errors={errors}")
	if dry_run:
		_log("Dry run complete. Re-run with dry_run=False to apply changes.")


# ---------------- Debug / Introspection Utilities ---------------- #

def _safe_dir(obj):
	try:
		return dir(obj)
	except Exception:
		return []


def _is_data_leaf(value):
	return isinstance(value, (int, float, str, bool)) or value is None


def introspect_object(obj, name="root", depth=0, visited=None, max_depth=INTROSPECT_MAX_DEPTH, max_children=INTROSPECT_MAX_CHILDREN):
	"""Recursively log accessible editor properties / attributes to help locate reduction settings path.

	We try get_editor_property for Unreal UObject derived instances and fall back to getattr for Python attributes.
	"""
	if visited is None:
		visited = set()
	try:
		obj_id = (id(obj), getattr(obj, 'get_name', lambda: type(obj).__name__)())
	except Exception:
		obj_id = (id(obj), type(obj).__name__)
	if obj_id in visited:
		return
	visited.add(obj_id)

	prefix = '  ' * depth
	try:
		type_name = type(obj).__name__
	except Exception:
		type_name = '<unknown>'
	unreal.log(f"[percenttriangles][INTROSPECT]{prefix}{name} : {type_name}")

	if depth >= max_depth:
		return

	# Collect candidate attribute/property names
	attr_names = []
	if hasattr(obj, 'get_editor_property'):  # Unreal UObject
		# Attempt to read property list via dir()
		attr_names.extend([a for a in _safe_dir(obj) if not a.startswith('__')])
	else:
		attr_names.extend([a for a in _safe_dir(obj) if not a.startswith('__')])

	shown = 0
	for attr in sorted(set(attr_names)):
		if not INTROSPECT_INCLUDE_PRIVATE and attr.startswith('_'):
			continue
		if shown >= max_children:
			unreal.log(f"[percenttriangles][INTROSPECT]{prefix}... child limit reached ...")
			break
		value = None
		got = False
		# Prefer editor property access first
		if hasattr(obj, 'get_editor_property'):
			try:
				value = obj.get_editor_property(attr)
				got = True
			except Exception:
				pass
		if not got:
			try:
				value = getattr(obj, attr)
			except Exception:
				continue
		try:
			v_type = type(value).__name__
		except Exception:
			v_type = '<unknown>'
		# Print leaf or brief container summary
		if _is_data_leaf(value):
			unreal.log(f"[percenttriangles][INTROSPECT]{prefix}- {attr} = {value!r} ({v_type})")
		elif isinstance(value, (list, tuple)):  # show size and maybe first element
			unreal.log(f"[percenttriangles][INTROSPECT]{prefix}- {attr} : {v_type}[len={len(value)}]")
			if value and depth + 1 <= max_depth:
				# Recurse into first few entries
				for idx, item in enumerate(value[: min(3, len(value))]):
					introspect_object(item, name=f"{attr}[{idx}]", depth=depth + 1, visited=visited, max_depth=max_depth, max_children=max_children)
		else:
			unreal.log(f"[percenttriangles][INTROSPECT]{prefix}- {attr} : {v_type}")
			# Recurse deeper
			try:
				introspect_object(value, name=attr, depth=depth + 1, visited=visited, max_depth=max_depth, max_children=max_children)
			except Exception:
				pass
		shown += 1


def debug_introspect_first_mesh(token=NAME_TOKEN, max_depth=INTROSPECT_MAX_DEPTH):
	meshes = find_static_meshes_with_token(token)
	if not meshes:
		_log(f"No meshes found with token '{token}' to introspect")
		return
	mesh = meshes[0]
	_log(f"Introspecting first mesh: {mesh.get_name()}")
	introspect_object(mesh, name=mesh.get_name(), max_depth=max_depth)
	_log("Introspection complete. Search logs for 'reduction' or 'lod'.")


if __name__ == "__main__":
	# If run directly by the Python execution plugin, default to dry-run False for actual batch.
	import sys
	dry = False
	diagnose = True
	if "--apply" in sys.argv:
		dry = False
	if "--diagnose" in sys.argv:
		diagnose = True
	run(dry_run=dry, diagnose=diagnose)

