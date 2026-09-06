"""What a person actually pastes, turned into the page the adapter expects.

The paste path exists because the ES portal will not talk to a machine,
so the input arrives however a browser hands it over. Chrome's
`view-source:` view is the common case on a desktop: `Ctrl+U`, select
all, copy — and what lands is the *source viewer*, a table of line
numbers with the real markup HTML-escaped inside `td.line-content`
cells. Unwrap that back into the page. Anything else passes through.
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def normalize_pasted(html: str) -> str:
    if 'class="line-content"' not in html and "class='line-content'" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.select("td.line-content")
    if not cells:
        return html
    return "\n".join(cell.get_text() for cell in cells)
