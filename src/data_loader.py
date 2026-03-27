from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

import pandas as pd


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}

SHIFT_FILENAME = "Employee Shift data.xlsx"
BUS_ROUTES_FILENAME = "Bus Routes curent.xlsx"
GEO_FILENAME = "Geocoordinates.xlsx"
OVERVIEW_FILENAME = "Kuwait Route Optimization - Overview.xlsx"


@dataclass(frozen=True)
class DatasetPaths:
    data_dir: Path
    shift_data: Path
    bus_routes: Path
    geocoordinates: Path
    overview: Path


def discover_dataset_paths(project_root: Path) -> DatasetPaths:
    candidate_dirs = [
        project_root / "data",
        project_root.parent / "Dataset_aditya",
        project_root.parent / "datasets",
    ]
    for directory in candidate_dirs:
        shift_data = directory / SHIFT_FILENAME
        bus_routes = directory / BUS_ROUTES_FILENAME
        geocoordinates = directory / GEO_FILENAME
        overview = directory / OVERVIEW_FILENAME
        if all(path.exists() for path in (shift_data, bus_routes, geocoordinates, overview)):
            return DatasetPaths(
                data_dir=directory,
                shift_data=shift_data,
                bus_routes=bus_routes,
                geocoordinates=geocoordinates,
                overview=overview,
            )
    raise FileNotFoundError(
        "Could not find the required Excel datasets in "
        f"{', '.join(str(path) for path in candidate_dirs)}."
    )


def workbook_sheet_names(path: Path) -> list[str]:
    with ZipFile(path) as workbook:
        root = ET.fromstring(workbook.read("xl/workbook.xml"))
        sheets = root.find("main:sheets", NS)
        if sheets is None:
            return []
        return [sheet.attrib["name"] for sheet in sheets]


def load_workbook_sheets_raw(path: Path) -> dict[str, pd.DataFrame]:
    return {sheet_name: read_xlsx_sheet_raw(path, sheet_name) for sheet_name in workbook_sheet_names(path)}


def read_xlsx_sheet_raw(path: Path, sheet_name: str) -> pd.DataFrame:
    with ZipFile(path) as workbook:
        shared_strings = _load_shared_strings(workbook)
        target = _sheet_target(workbook, sheet_name)
        sheet_root = ET.fromstring(workbook.read(target))
        cells: dict[tuple[int, int], object] = {}
        max_row = -1
        max_col = -1

        for row in sheet_root.findall(".//main:sheetData/main:row", NS):
            row_ref = int(row.attrib.get("r", "1")) - 1
            max_row = max(max_row, row_ref)
            for cell in row.findall("main:c", NS):
                ref = cell.attrib.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                col_ref = _column_letters_to_index(col_letters)
                max_col = max(max_col, col_ref)
                cells[(row_ref, col_ref)] = _cell_value(cell, shared_strings)

        if max_row < 0 or max_col < 0:
            return pd.DataFrame()

        matrix: list[list[object]] = [[None] * (max_col + 1) for _ in range(max_row + 1)]
        for (row_ref, col_ref), value in cells.items():
            matrix[row_ref][col_ref] = value
        return pd.DataFrame(matrix)


def _sheet_target(workbook: ZipFile, sheet_name: str) -> str:
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    rel_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    relationship_lookup = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall("pkg:Relationship", NS)
    }
    sheets = workbook_root.find("main:sheets", NS)
    if sheets is None:
        raise KeyError(f"No sheets found in workbook {workbook.filename}.")

    for sheet in sheets:
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{NS['rel']}}}id")
        if rel_id is None:
            break
        target = relationship_lookup[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        return target
    raise KeyError(f"Sheet '{sheet_name}' not found in workbook {workbook.filename}.")


def _load_shared_strings(workbook: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", NS):
        texts = [text.text or "" for text in item.iterfind(".//main:t", NS)]
        values.append("".join(texts))
    return values


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    inline = cell.find("main:is", NS)
    if inline is not None:
        texts = [text.text or "" for text in inline.iterfind(".//main:t", NS)]
        return "".join(texts)

    value_node = cell.find("main:v", NS)
    if value_node is None:
        return None

    raw_value = value_node.text or ""
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        index = int(raw_value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else None
    if cell_type == "b":
        return raw_value == "1"
    if cell_type == "str":
        return raw_value
    if re.fullmatch(r"-?\d+", raw_value):
        return int(raw_value)
    if re.fullmatch(r"-?\d*\.\d+(E[+-]?\d+)?", raw_value, flags=re.IGNORECASE):
        return float(raw_value)
    return raw_value


def _column_letters_to_index(value: str) -> int:
    total = 0
    for ch in value:
        if ch.isalpha():
            total = total * 26 + (ord(ch.upper()) - 64)
    return max(total - 1, 0)
