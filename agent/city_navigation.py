"""Exact authorized-file lookup in MY Q, with a serial filter when necessary."""
import re


def find_bank_row(page, serial):
    if not isinstance(serial, str) or not re.fullmatch(r'\d+', serial):
        raise RuntimeError('Bank lookup needs a numeric string serial, preserving zeros.')
    serial_cell = page.locator("div[role='gridcell'][columnindex='6']").filter(
        has_text=re.compile(r'(?:^|-)'+re.escape(serial)+r'$'))
    rows = page.locator("div[role='row']").filter(has=serial_cell)
    if rows.count() == 0:
        field = page.locator('#file_serial_no')
        search = page.locator('#grid_search')
        if field.count() != 1 or search.count() != 1:
            raise RuntimeError('Target not visible and bank serial filter is unavailable.')
        field.fill(serial)
        search.click()
        rows.wait_for(state='visible', timeout=60000)
    if rows.count() != 1:
        raise RuntimeError('Bank target is missing or ambiguous after exact serial lookup.')
    row = rows.first
    actual = row.locator("[role='gridcell'][columnindex='6']").inner_text().strip()
    if actual.split('-')[-1] != serial:
        raise RuntimeError('Filtered bank serial differs from the authorized target.')
    return row
