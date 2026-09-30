"""Seb's workbook -> manifest rows (backend/services/gallery_sheet.py)."""
from __future__ import annotations

import openpyxl

from backend.services import gallery_sheet

HEAD = ["Section", "Id", "Video Title", "Proposed Title", "Delete?", "Short Description",
        "Long Description", "Tags", "Proposed Tags", "Segment", "Customer Facing?", "Current?",
        "Video Type", "Subtype", "Published Date"]


def book(tmp_path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(HEAD)
        for r in rows:
            ws.append(r)
    path = tmp_path / "v29.xlsx"
    wb.save(path)
    return str(path)


def video(bcid, tags="Creo", current=True):
    return ["CAD - All", bcid, "A video", None, False, "Short", "Long", "", tags, "CAD", True,
            current, "Technical Overview", "Feature", None]


def test_the_xdp_vdks_sheet_is_skipped(tmp_path):
    """Seb, via Elio, 2026-09-30: those are loaded another way."""
    rows, report = gallery_sheet.read(book(tmp_path, {
        "XDP VDKs": [video("6300000000001")],
        "CAD (PTC Gallery)": [video("6300000000002")]}))
    assert [r["brightcove_id"] for r in rows] == ["6300000000002"]
    assert report["skipped_sheets"] == ["XDP VDKs"]


def test_current_is_carried_into_the_manifest(tmp_path):
    rows, _ = gallery_sheet.read(book(tmp_path, {"CAD (PTC Gallery)": [
        video("6300000000001", current=True), video("6300000000002", current=False)]}))
    assert [r["current"] for r in rows] == ["yes", "no"]


def test_two_unambiguous_product_typos_are_mapped():
    products, customers = gallery_sheet.split_tags("Creo, Creo Creo Simulation Live, Creo Ai")
    assert products == ["Creo", "Creo Simulation Live", "Creo AI"]
    assert customers == []
