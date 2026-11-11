"""Read-only City Bank MIS completion gate, shared by discovery and upload.

Only a positively read blank MIS status is eligible. Green Received (Full) rows
are skipped. Missing columns/cells, conflicting colors and other statuses require
review, never a guess that the file is pending. No portal requests are made here.
"""
import re


def _green(color):
    match = re.fullmatch(r'rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)', color or '')
    if not match:
        return False
    red, green, blue = map(float, match.group(1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) is not None else 1
    return alpha > 0 and green >= 64 and green > red * 1.2 and green > blue * 1.2


def classify_mis_status(text, colors):
    """Return skip/eligible/review; never substring-match partial/full statuses."""
    text = ' '.join((text or '').split())
    normalized = re.sub(r'[^a-z0-9]', '', text.casefold())
    green = bool(colors) and all(_green(color) for color in colors)
    if normalized in {'receivedfull', 'receivedfully', 'fullyreceived'} and green:
        decision = 'skip_received_full'
    elif not text:
        decision = 'eligible_blank'
    else:
        decision = 'review_nonblank_status'
    return {'text': text, 'colors': colors, 'green': green, 'decision': decision,
            'skip': decision == 'skip_received_full',
            'eligible': decision == 'eligible_blank'}


def check_mis_status(row):
    """Read the actual status cell and computed font colors in a jqx-grid row.

    Resolve by the MIS header, not a hardcoded column number: column positions
    can change with grid layout. Missing/ambiguous metadata fails closed.
    """
    observed = row.evaluate(r'''row => {
        const grid = row.closest('.jqx-grid, [role="grid"]');
        if (!grid) return {error:'City Bank grid not found'};
        const canonical = value => (value || '').toLowerCase().replace(/[^a-z0-9]/g,'');
        const titles = new Set(['misreportreceivestatus','misreportreceivedstatus']);
        const headers = [...grid.querySelectorAll('[role="columnheader"]')];
        const matches = headers.filter(h => titles.has(canonical(h.innerText || h.textContent)));
        if (matches.length !== 1) return {error:'MIS status header is missing or ambiguous'};
        const header = matches[0];
        let index = header.getAttribute('columnindex');
        if (index === null && header.hasAttribute('aria-colindex'))
            index = String(Number(header.getAttribute('aria-colindex')) - 1);
        // jqxGrid keeps logical columns even when some are offscreen or hidden.
        if (index === null && window.jQuery && window.jQuery.fn.jqxGrid) {
            try {
                const columns = window.jQuery(grid).jqxGrid('columns');
                const records = columns && columns.records;
                if (Array.isArray(records)) {
                    const candidates = records.map((c,i) => ({c,i})).filter(
                        item => titles.has(canonical(item.c.text)));
                    if (candidates.length === 1) index = String(candidates[0].i);
                }
            } catch (_) { /* Fall through only to an unambiguous DOM layout. */ }
        }
        const cells = [...row.querySelectorAll('[role="gridcell"][columnindex]')];
        if (index === null && headers.length === cells.length &&
            cells.every((cell,i) => Number(cell.getAttribute('columnindex')) === i))
            index = String(headers.indexOf(header));
        if (index === null || !/^\d+$/.test(index))
            return {error:'Cannot resolve the MIS status column safely'};
        const statusCells = cells.filter(cell => cell.getAttribute('columnindex') === index);
        if (statusCells.length !== 1) return {error:'MIS status cell is missing or ambiguous'};
        const cell = statusCells[0];
        if (!cell.getClientRects().length || getComputedStyle(cell).visibility !== 'visible')
            return {error:'MIS status cell is not rendered'};
        const colors = [];
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            if (!node.textContent.trim()) continue;
            const parent = node.parentElement;
            if (!parent || !parent.getClientRects().length) continue;
            const style = getComputedStyle(parent);
            if (style.visibility === 'visible' && style.display !== 'none')
                colors.push(style.color);
        }
        return {text:cell.innerText.trim(), colors,
                column_index:Number(index), header:header.innerText.trim()};
    }''')
    if observed.get('error'):
        raise RuntimeError('MIS completion check blocked: ' + observed['error'])
    result = classify_mis_status(observed['text'], observed['colors'])
    result.update(column_index=observed['column_index'], header=observed['header'])
    if not result['skip'] and not result['eligible']:
        raise RuntimeError(
            f"MIS status {result['text']!r} is not blank or confirmed green Received (Full); "
            'operator review is required before working on this file.')
    return result
