import json
import os
import re
from glob import glob
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import win32com.client

from BuildOptionReaper import filter_code_by_build_options
from CallerExtractor import resolve_caller_function
from FunctionBodyExtractor import get_function_body


# =========================
#  Config
# =========================
LAYER_PREFIX = "HIL"
RAW_FOLDER = r"C:\Users\me\path1\blabla"
CODE_PATH_MAP = "code_path_map.json"
SWE2_WORKITEM = "SWE2_WorkItem.xlsx"
SOURCES_JSON = "sources.json"

RESULT_ROOT = "Results"
LOG_FOLDER = "log"

LOG_TARGET_BODY = os.path.join(LOG_FOLDER, "log_target_body_not_found.txt")
LOG_CALLER = os.path.join(LOG_FOLDER, "log_caller_resolution.txt")
LOG_WORKITEM = os.path.join(LOG_FOLDER, "log_swe2_lookup.txt")
LOG_SKIP = os.path.join(LOG_FOLDER, "log_skipped_entries.txt")
LOG_SYSTEM = os.path.join(LOG_FOLDER, "log_system_errors.txt")

RAW_SHEET_NAME = "Unit_Interface"


# =========================
#  Helpers
# =========================
def ensure_output_dirs() -> None:
    os.makedirs(RESULT_ROOT, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def normalize_space(value) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def normalize_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_space(value).lower())


def normalize_component(value) -> str:
    return normalize_key(value)


def layer_token() -> str:
    return clean_text(LAYER_PREFIX).strip("_")


def layer_prefix() -> str:
    token = layer_token()
    return f"{token}_" if token else ""


def load_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def dataframe_from_used_range(data, path: str) -> pd.DataFrame:
    if data is None:
        raise ValueError(f"{path}: target sheet is empty.")

    if not isinstance(data, tuple):
        data = ((data,),)
    elif data and not isinstance(data[0], tuple):
        data = (data,)

    header = list(data[0])
    rows = list(data[1:])
    return pd.DataFrame(rows, columns=header)


def load_sheet_dataframe(
    path: str,
    preferred_sheet: Optional[str] = None,
    excel_app=None,
) -> pd.DataFrame:
    owns_app = excel_app is None
    xl = excel_app or win32com.client.Dispatch("Excel.Application")
    xl.Visible = False

    workbook = xl.Workbooks.Open(os.path.abspath(path))
    try:
        if preferred_sheet:
            try:
                worksheet = workbook.Worksheets(preferred_sheet)
            except Exception:
                worksheet = workbook.Worksheets(1)
        else:
            worksheet = workbook.Worksheets(1)

        data = worksheet.UsedRange.Value
    finally:
        workbook.Close(SaveChanges=False)
        if owns_app:
            xl.Quit()

    return dataframe_from_used_range(data, path)


def choose_column(
    df: pd.DataFrame,
    exact_candidates: Iterable[str],
    contains_candidates: Iterable[str] = (),
    required: bool = True,
) -> Optional[str]:
    columns = list(df.columns)
    normalized = {normalize_space(col).lower(): col for col in columns if clean_text(col)}

    for candidate in exact_candidates:
        key = normalize_space(candidate).lower()
        if key in normalized:
            return normalized[key]

    for candidate in exact_candidates:
        key = normalize_key(candidate)
        for col in columns:
            if normalize_key(col) == key:
                return col

    for needle in contains_candidates:
        needle_key = normalize_key(needle)
        for col in columns:
            if needle_key and needle_key in normalize_key(col):
                return col

    if required:
        raise KeyError(f"Required column not found. Candidates: {list(exact_candidates)}")
    return None


def extract_component_from_excel_name(path: str) -> str:
    stem = Path(path).stem
    prefix = layer_prefix()
    if prefix and stem.upper().startswith(prefix.upper()):
        return stem[len(prefix):]
    return stem


def parse_interface_id(interface_id: str, component: str) -> str:
    body = clean_text(interface_id)
    prefix = re.escape(layer_token())
    body = re.sub(rf"^(?:IF_)?{prefix}_", "", body, flags=re.IGNORECASE)
    body = re.sub(r"_\d+$", "", body)

    match = re.match(rf"^{re.escape(component)}_(.+)$", body, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    return body


def parse_source_destination(value) -> List[Tuple[str, str]]:
    text = clean_text(value)
    if not text:
        return []

    entries = []
    for part in re.split(r"[,;\n]+", text):
        token = part.strip()
        if not token or "/" not in token:
            continue

        component, unit = token.split("/", 1)
        component = component.strip()
        unit = unit.strip()
        if component and unit:
            entries.append((component, unit))

    return entries


def first_external_caller(
    source_destination,
    target_component: str,
) -> Optional[Tuple[str, str]]:
    target_key = normalize_component(target_component)
    for component, unit in parse_source_destination(source_destination):
        if normalize_component(component) != target_key:
            return component, unit
    return None


def discover_raw_excel_files() -> List[str]:
    files = []
    prefix = layer_prefix() or ""
    for pattern in (f"{prefix}*.xlsm", f"{prefix}*.xlsx", f"{prefix}*.xls"):
        files.extend(glob(os.path.join(RAW_FOLDER, pattern)))
    return sorted(set(files))


def find_component_excel(component: str) -> str:
    prefix = layer_prefix()
    for ext in ("xlsm", "xlsx", "xls"):
        candidate = os.path.join(RAW_FOLDER, f"{prefix}{component}.{ext}")
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"Raw excel for component '{component}' was not found in RAW_FOLDER.")


def resolve_code_map_entry(mapping: dict, target_key: str):
    exact = mapping.get(target_key)
    if exact is not None:
        return exact

    target_norm = normalize_key(target_key)
    for key, value in mapping.items():
        if normalize_key(key) == target_norm:
            return value

    return None


def candidate_code_files(path_hint: str) -> List[str]:
    hint = Path(path_hint)
    base = hint.with_suffix("")

    candidates = [
        str(hint),
        str(base.with_suffix(".h")),
        str(base.with_suffix(".cpp")),
    ]

    ordered = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)

    return ordered


class SWE2FunctionIndex:
    def __init__(self, workbook_path: str, sources_map: dict, excel_app=None) -> None:
        self.df = load_sheet_dataframe(workbook_path, excel_app=excel_app)
        self.title_col = choose_column(self.df, ["Title"])
        self.id_col = choose_column(self.df, ["ID"])
        self.link_cols = [
            column
            for column in self.df.columns
            if "linkedworkitems" in normalize_key(column) or "hasparents" in normalize_key(column)
        ]

        self.sources_map = {clean_text(key).upper(): clean_text(value) for key, value in sources_map.items()}
        self.title_map: Dict[str, List[int]] = {}

        valid_df = self.df[self.df[self.title_col].notnull()].copy()
        for idx, row in valid_df.iterrows():
            title_key = normalize_space(row[self.title_col]).lower()
            if title_key:
                self.title_map.setdefault(title_key, []).append(idx)

    def _row_components(self, row: pd.Series) -> List[str]:
        components = []
        for column in self.link_cols:
            text = clean_text(row.get(column))
            if not text:
                continue

            for match in re.finditer(r"has\s*parents\s*:\s*([^\n\r;]+)", text, flags=re.IGNORECASE):
                for parent_id in re.findall(r"[A-Za-z][A-Za-z0-9-]*-\d+", match.group(1)):
                    component = self.sources_map.get(parent_id.upper())
                    if component:
                        components.append(component)

        return components

    def lookup_function_id(self, component: str, unit: str, function_name: str) -> Tuple[str, List[Tuple[str, str]]]:
        title_key = f"{unit} {function_name}".strip().lower()
        indices = self.title_map.get(title_key, [])
        errors: List[Tuple[str, str]] = []

        if not indices:
            errors.append(("NO TITLE", "Title not found in SWE2_WorkItem workbook."))
            return "", errors

        if len(indices) == 1:
            row = self.df.loc[indices[0]]
            return clean_text(row.get(self.id_col)), errors

        target_component = normalize_component(component)
        valid = []
        for idx in indices:
            row = self.df.loc[idx]
            components = [normalize_component(item) for item in self._row_components(row)]
            if target_component and target_component in components:
                valid.append(idx)

        if len(valid) != 1:
            errors.append(
                (
                    "DUPLICATE",
                    f"{len(valid)} candidates remain after sources.json parent filtering.",
                )
            )
            return "", errors

        row = self.df.loc[valid[0]]
        return clean_text(row.get(self.id_col)), errors


class ProjectContext:
    def __init__(self, code_path_map: dict, swe2_index: SWE2FunctionIndex, excel_app) -> None:
        self.code_path_map = code_path_map
        self.swe2_index = swe2_index
        self.excel_app = excel_app
        self.raw_excel_cache: Dict[str, pd.DataFrame] = {}
        self.filtered_file_cache: Dict[str, str] = {}
        self.unit_bundle_cache: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        self.function_body_cache: Dict[Tuple[str, str, str], str] = {}

    def load_component_raw_df(self, component: str) -> pd.DataFrame:
        cache_key = normalize_space(component)
        if cache_key not in self.raw_excel_cache:
            path = find_component_excel(component)
            self.raw_excel_cache[cache_key] = load_sheet_dataframe(
                path,
                preferred_sheet=RAW_SHEET_NAME,
                excel_app=self.excel_app,
            )
        return self.raw_excel_cache[cache_key]

    def _resolve_unit_paths(self, component: str, unit: str) -> List[str]:
        component_map = resolve_code_map_entry(self.code_path_map, component)
        if not component_map:
            return []

        unit_paths = resolve_code_map_entry(component_map, unit)
        if not unit_paths:
            return []

        if isinstance(unit_paths, list):
            return [clean_text(path) for path in unit_paths if clean_text(path)]
        if clean_text(unit_paths):
            return [clean_text(unit_paths)]
        return []

    def _read_filtered_code(self, file_path: str) -> str:
        if file_path not in self.filtered_file_cache:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
                self.filtered_file_cache[file_path] = filter_code_by_build_options(file.read())
        return self.filtered_file_cache[file_path]

    def unit_code_bundle(self, component: str, unit: str) -> List[Tuple[str, str]]:
        cache_key = (normalize_key(component), normalize_key(unit))
        if cache_key in self.unit_bundle_cache:
            return self.unit_bundle_cache[cache_key]

        bundle: List[Tuple[str, str]] = []
        seen = set()

        for path_hint in self._resolve_unit_paths(component, unit):
            for candidate in candidate_code_files(path_hint):
                if candidate in seen or not os.path.exists(candidate):
                    continue
                seen.add(candidate)
                bundle.append((candidate, self._read_filtered_code(candidate)))

        self.unit_bundle_cache[cache_key] = bundle
        return bundle

    def find_function_body(self, component: str, unit: str, function_name: str) -> str:
        cache_key = (normalize_key(component), normalize_key(unit), normalize_space(function_name))
        if cache_key in self.function_body_cache:
            return self.function_body_cache[cache_key]

        bundle = self.unit_code_bundle(component, unit)
        search_classes = [unit, None] if normalize_space(unit) else [None]

        body = ""
        for _, code in bundle:
            for class_name in search_classes:
                body = get_function_body(code, function_name, class_name=class_name)
                if body:
                    break
            if body:
                break

        if not body and bundle:
            combined = "\n\n".join(code for _, code in bundle)
            for class_name in search_classes:
                body = get_function_body(combined, function_name, class_name=class_name)
                if body:
                    break

        self.function_body_cache[cache_key] = body
        return body

    def resolve_caller(self, target_component: str, target_function: str, source_destination) -> dict:
        caller_location = first_external_caller(source_destination, target_component)
        if not caller_location:
            return {
                "skip_entry": True,
                "reason": "All caller units belong to the same component.",
                "caller_component": "",
                "caller_unit": "",
                "caller_function_id": "",
                "caller_function_name": "",
                "caller_function_body": "",
            }

        caller_component, caller_unit = caller_location
        caller_df = self.load_component_raw_df(caller_component)
        interface_id_col = choose_column(caller_df, ["Interface ID"], ["interfaceid"])
        function_name_col = choose_column(caller_df, ["Interface Name"], ["interfacename", "functionname"])

        interface_pairs = []
        for _, row in caller_df.iterrows():
            interface_id = clean_text(row.get(interface_id_col))
            function_name = clean_text(row.get(function_name_col))
            if not interface_id or not function_name:
                continue

            row_unit = parse_interface_id(interface_id, caller_component)
            if normalize_key(row_unit) != normalize_key(caller_unit):
                continue

            interface_pairs.append((interface_id, function_name))

        bundle = self.unit_code_bundle(caller_component, caller_unit)
        caller_code = "\n\n".join(code for _, code in bundle)

        resolution = resolve_caller_function(
            caller_code,
            target_function_name=target_function,
            interface_pairs=interface_pairs,
            class_name=caller_unit,
        )

        resolution.update(
            {
                "skip_entry": False,
                "reason": "",
                "caller_component": caller_component,
                "caller_unit": caller_unit,
            }
        )
        return resolution


def save_log(path: str, entries: List[str]) -> bool:
    if not entries:
        return False

    with open(path, "w", encoding="utf-8") as file:
        file.write("\n\n".join(entries))
    return True


def main() -> None:
    ensure_output_dirs()

    code_path_map = load_json_file(CODE_PATH_MAP)
    sources_map = load_json_file(SOURCES_JSON)

    raw_excel_files = discover_raw_excel_files()
    if not raw_excel_files:
        raise FileNotFoundError("No HIL_*.xls* raw excel files were found in RAW_FOLDER.")

    excel_app = win32com.client.Dispatch("Excel.Application")
    excel_app.Visible = False

    log_target_body: List[str] = []
    log_caller: List[str] = []
    log_workitem: List[str] = []
    log_skip: List[str] = []
    log_system: List[str] = []
    all_rows: List[dict] = []

    try:
        swe2_index = SWE2FunctionIndex(SWE2_WORKITEM, sources_map, excel_app=excel_app)
        context = ProjectContext(code_path_map, swe2_index, excel_app)

        for xls_file in raw_excel_files:
            component = extract_component_from_excel_name(xls_file)

            try:
                df = load_sheet_dataframe(xls_file, preferred_sheet=RAW_SHEET_NAME, excel_app=excel_app)
                interface_id_col = choose_column(df, ["Interface ID"], ["interfaceid"])
                function_name_col = choose_column(df, ["Interface Name"], ["interfacename", "functionname"])
                source_destination_col = choose_column(
                    df,
                    ["Source/Destination"],
                    ["sourcedestination", "source", "destination"],
                    required=False,
                )

                for _, row in df.iterrows():
                    interface_id = clean_text(row.get(interface_id_col))
                    function_name = clean_text(row.get(function_name_col))
                    if not interface_id or not function_name:
                        continue

                    unit = parse_interface_id(interface_id, component)

                    try:
                        source_destination = row.get(source_destination_col) if source_destination_col else None

                        caller_info = context.resolve_caller(component, function_name, source_destination)
                        if caller_info["skip_entry"]:
                            log_skip.append(
                                f"[INTERNAL ONLY] {component}/{unit}/{function_name}: {caller_info['reason']}"
                            )
                            continue

                        target_body = context.find_function_body(component, unit, function_name)
                        if not target_body:
                            log_target_body.append(
                                f"[NOT FOUND] {component}/{unit}/{function_name}: target function body not found."
                            )

                        target_function_id, workitem_errors = swe2_index.lookup_function_id(
                            component,
                            unit,
                            function_name,
                        )
                        for error_type, reason in workitem_errors:
                            log_workitem.append(
                                f"[{error_type}] {component}/{unit}/{function_name}: {reason}"
                            )

                        if not caller_info["caller_function_id"]:
                            log_caller.append(
                                f"[NOT FOUND] {component}/{unit}/{function_name}: "
                                f"caller resolution failed for {caller_info['caller_component']}/"
                                f"{caller_info['caller_unit']}."
                            )

                        if caller_info["caller_function_id"] and not caller_info["caller_function_body"]:
                            log_caller.append(
                                f"[BODY EMPTY] {component}/{unit}/{function_name}: "
                                f"caller function body not expanded for {caller_info['caller_function_id']}."
                            )

                        all_rows.append(
                            {
                                "Component": component,
                                "Unit": unit,
                                "Function": function_name,
                                "Caller Function ID": caller_info["caller_function_id"],
                                "Caller Function Body": caller_info["caller_function_body"],
                                "Target Function Body": target_body,
                                "Linked Work Items": target_function_id,
                            }
                        )

                    except Exception as exc:
                        log_system.append(
                            f"[ROW] Error while processing {component}/{unit}/{function_name}: {exc}"
                        )

            except Exception as exc:
                log_system.append(f"[SYSTEM] Error while processing {xls_file}: {exc}")

    finally:
        excel_app.Quit()

    if all_rows:
        df_final = pd.DataFrame(all_rows)
        for (component, unit), group in df_final.groupby(["Component", "Unit"]):
            component_folder = os.path.join(RESULT_ROOT, component)
            os.makedirs(component_folder, exist_ok=True)

            out_path = os.path.join(component_folder, f"{component}_{unit}.xlsx")
            export_df = group[
                [
                    "Component",
                    "Unit",
                    "Function",
                    "Caller Function ID",
                    "Caller Function Body",
                    "Target Function Body",
                    "Linked Work Items",
                ]
            ]
            export_df.to_excel(out_path, index=False)

    written_logs = [
        save_log(LOG_TARGET_BODY, log_target_body),
        save_log(LOG_CALLER, log_caller),
        save_log(LOG_WORKITEM, log_workitem),
        save_log(LOG_SKIP, log_skip),
        save_log(LOG_SYSTEM, log_system),
    ]

    if any(written_logs):
        print("[INFO] Processing completed with logs. Check the log folder for details.")
    else:
        print("[INFO] Processing completed without logged issues.")


if __name__ == "__main__":
    main()
