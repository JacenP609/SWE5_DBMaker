import os
import json
import re
from glob import glob

import pandas as pd
import win32com.client

from FunctionBodyExtractor import get_function_body
from BuildOptionReaper import filter_code_by_build_options

# =========================
#  CONFIG
# =========================
# place where all the data function resides
RAW_FOLDER = r"C:\Users\me\path1\blabla"
CODE_PATH_MAP = r"code_path_map.json"
SWE3_WORKITEM = r"SWE3_WorkItem.xlsx"

RESULT_ROOT = "Results"
LOG_FOLDER = "log"

os.makedirs(RESULT_ROOT, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

LOG_NOT_FOUND = os.path.join(LOG_FOLDER, "log_not_found.txt")
LOG_SWE3 = os.path.join(LOG_FOLDER, "log_swe3_error.txt")


# =========================
#  Load first sheet using pywin32
# =========================
def load_single_sheet(path: str) -> pd.DataFrame:
    xl = win32com.client.Dispatch("Excel.Application")
    xl.Visible = False
    wb = xl.Workbooks.Open(os.path.abspath(path))
    ws = wb.Worksheets(1)
    used = ws.UsedRange
    data = used.Value
    wb.Close(SaveChanges=False)
    xl.Quit()

    if data is None:
        raise ValueError(f"{path}: 첫 번째 시트가 비어 있습니다.")

    header = list(data[0])
    rows = data[1:]
    return pd.DataFrame(rows, columns=header)


# =========================
#  Load SWE3 WorkItem
# =========================
swe3_df = load_single_sheet(SWE3_WORKITEM)
swe3_df = swe3_df[swe3_df["Title"].notnull()].copy()
swe3_df["__norm_title__"] = swe3_df["Title"].map(lambda x: str(x).strip().lower())

linked_cols = [
    c for c in swe3_df.columns
    if isinstance(c, str) and c.strip().startswith("Linked Work Items")
]
if not linked_cols:
    raise ValueError("SWE3_WorkItem.xlsx 에 'Linked Work Items' 컬럼이 없습니다.")

SWE3_LINK_COL = linked_cols[0]

swe3_title_map = {}
for idx, row in swe3_df.iterrows():
    key = row["__norm_title__"]
    swe3_title_map.setdefault(key, []).append(idx)


# =========================
#  Load SCU Items
# =========================
scu_df = load_single_sheet(SCU_ITEMS)
scu_id_to_comp = {}

for _, row in scu_df.iterrows():
    sid = str(row["ID"]).strip()
    title = str(row["Title"]).strip()
    if not sid or not title:
        continue

    parts = title.split()
    if parts:
        scu_id_to_comp[sid] = parts[0].lower()


# =========================
#  classify UI/CI
# =========================
def classify_interface(src, component):
    if src is None or (isinstance(src, float) and pd.isna(src)):
        return "CI"

    txt = str(src).strip()
    if not txt:
        return "CI"

    parts = re.split(r'[,;\n]+', txt)
    comps = []

    for p in parts:
        t = p.strip()
        if not t:
            continue
        if "/" in t:
            c, _ = t.split("/", 1)
            comps.append(c.strip())
        else:
            comps.append(t)

    if not comps:
        return "CI"

    if all(c.lower() == component.lower() for c in comps):
        return "UI"
    return "CI"


# =========================
#  Interface ID → Unit
# =========================
def parse_interface_id(ifid, comp):
    body = ifid.removeprefix("IF_HIL_")
    body = re.sub(r'_\d+$', '', body)

    prefix = f"{comp}_"
    if body.startswith(prefix):
        return body[len(prefix):]

    return body.rsplit("_", 1)[-1]


# =========================
#  implements 추출
# =========================
def extract_implements(text):
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None, ("IMPLEMENTS-0", "implements entry not found.")

    t = str(text).strip()
    if not t:
        return None, ("IMPLEMENTS-0", "implements entry not found.")

    segs = [s.strip() for s in t.split(",") if s.strip()]
    impl_ids = []

    for seg in segs:
        m = re.search(r'implements\s*:\s*([A-Za-z0-9]+-\d+)', seg, flags=re.IGNORECASE)
        if m:
            impl_ids.append(m.group(1).upper())

    if len(impl_ids) != 1:
        if len(impl_ids) == 0:
            return None, ("IMPLEMENTS-0", "no implements entry found.")
        return None, ("IMPLEMENTS-2+", "multiple implements entries found.")

    return impl_ids[0], None


# =========================
#  SWE3 lookup logic
# =========================
def lookup_swe3(component, unit, func):
    key = f"{unit} {func}".lower()
    indices = swe3_title_map.get(key, [])

    errors = []

    # 0) Title 매칭 없음
    if len(indices) == 0:
        errors.append(("NO TITLE", "Title not found in SWE3_WorkItem."))
        return "", "", errors

    # 1) Unique match
    if len(indices) == 1:
        idx = indices[0]
        row = swe3_df.loc[idx]

        impl_id, impl_err = extract_implements(row.get(SWE3_LINK_COL))
        if impl_err:
            errors.append(impl_err)
            return "", "", errors

        risk = str(row.get("Risk", "")).strip()
        wid = str(row.get("ID", "")).strip()
        linked = f"Verifies: {wid}" if wid else ""
        return risk, linked, errors

    # 2) Duplicates → SCU filtering
    valid = []

    for idx in indices:
        row = swe3_df.loc[idx]
        impl_id, impl_err = extract_implements(row.get(SWE3_LINK_COL))

        if impl_err or not impl_id:
            errors.append(impl_err)
            continue

        scu_comp = scu_id_to_comp.get(impl_id)
        if not scu_comp:
            errors.append(("SCU NOTFOUND", "implements ID not found in SCU sheet."))
            continue

        if scu_comp == component.lower():
            valid.append(idx)

    if len(valid) != 1:
        errors.append(("DUPLICATE", f"{len(valid)} candidates remain after SCU filtering."))
        return "", "", errors

    idx = valid[0]
    row = swe3_df.loc[idx]
    risk = str(row.get("Risk", "")).strip()
    wid = str(row.get("ID", "")).strip()
    linked = f"Verifies: {wid}" if wid else ""

    return risk, linked, errors


# =========================
#  MAIN
# =========================
def main():

    with open(CODE_PATH_MAP, "r", encoding="utf-8") as f:
        code_path_map = json.load(f)

    xl = win32com.client.Dispatch("Excel.Application")
    xl.Visible = False

    log_nf = []   # Function Body Not Found
    log_swe = []  # SWE3 Matching Errors

    all_rows = []

    file_list = glob(os.path.join(RAW_FOLDER, "HIL_*.xlsm"))

    for xls_file in file_list:

        component = os.path.splitext(os.path.basename(xls_file))[0].replace("HIL_", "")

        try:
            wb = xl.Workbooks.Open(os.path.abspath(xls_file))
            ws = wb.Worksheets("Unit_Interface")
            used = ws.UsedRange
            data = used.Value
            wb.Close(SaveChanges=False)

            header = list(data[0])
            df = pd.DataFrame(data[1:], columns=header)
            df = df[df["Interface ID"].notnull()]

            for _, row in df.iterrows():

                ifid = row["Interface ID"]
                func = row["Interface Name"]
                src = row.get("Source/Destination", None)

                # Unit Name
                unit = parse_interface_id(ifid, component)

                # Internal/Component Interface 판정
                ui_ci = classify_interface(src, component)

                # SWE3 Lookup
                risk, linked, errors = lookup_swe3(component, unit, func)
                result_filename = f"{component}_{unit}.xlsx"

                for et, reason in errors:
                    log_swe.append(
                        f"[{et}] {component}/{unit}/{func} in Result({result_filename}):\n"
                        f"Reason: {reason}"
                    )

                # ============================================
                #        Function Body 추출
                # ============================================
                fbody = ""
                unit_paths = code_path_map.get(component, {}).get(unit, [])

                if unit_paths:
                    for header_path in unit_paths:

                        base, _ = os.path.splitext(header_path)

                        # cpp → h 순서대로 시도
                        candidates = [
                            base + ".cpp",
                            base + ".h"
                        ]

                        for file_path in candidates:
                            if not os.path.exists(file_path):
                                continue

                            # read raw code
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                raw = f.read()

                            # apply build option filter
                            filtered = filter_code_by_build_options(raw)

                            # ============================================
                            #        Function Body 추출부 모듈화
                            #        Build Option Reap Out 된 전체 STR 기반 작업 수행.
                            # ============================================
                            fbody = get_function_body(filtered, func, class_name=unit)

                            if fbody:  # found → stop searching
                                break

                        if fbody:
                            break

                if not fbody:
                    log_nf.append(
                        f"[NOT FOUND] {component}/{unit}/{func} in Result({result_filename})"
                    )

                # Save row
                all_rows.append({
                    "Component": component,
                    "Unit": unit,
                    "Function": func,
                    "UI/CI": ui_ci,
                    "Risk": risk,
                    "Function Body": fbody,
                    "Linked Work Items": linked,
                })

        except Exception as e:
            log_swe.append(f"[SYSTEM] Error while processing {xls_file}: {e}")

    xl.Quit()

    # ===================
    # Export result Excel
    # ===================
    df_final = pd.DataFrame(all_rows)

    for (comp, unit), group in df_final.groupby(["Component", "Unit"]):
        comp_folder = os.path.join(RESULT_ROOT, comp)
        os.makedirs(comp_folder, exist_ok=True)

        out_path = os.path.join(comp_folder, f"{comp}_{unit}.xlsx")

        export_df = group[
            ["Component", "Unit", "Function", "UI/CI",
             "Risk", "Function Body", "Linked Work Items"]
        ]
        export_df.to_excel(out_path, index=False)

    # ===================
    # Save logs
    # ===================
    nf_written = False
    swe_written = False

    if log_nf:
        with open(LOG_NOT_FOUND, "w", encoding="utf-8") as f:
            f.write("\n\n".join(log_nf))
        nf_written = True

    if log_swe:
        with open(LOG_SWE3, "w", encoding="utf-8") as f:
            f.write("\n\n".join(log_swe))
        swe_written = True

    # Console notification
    if nf_written or swe_written:
        print("\n[INFO] 에러 로그가 생성되었습니다. log 폴더의 파일을 확인하세요.")
        if nf_written:
            print(f" - Function Body Not Found Log: {LOG_NOT_FOUND}")
        if swe_written:
            print(f" - SWE3 Error Log: {LOG_SWE3}")
    else:
        print("\n[INFO] 에러 없이 모든 처리가 완료되었습니다.")


if __name__ == "__main__":
    main()
