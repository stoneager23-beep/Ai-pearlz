"""One consistent set of inline SVG icons (24 px grid, 1.5 px stroke, round caps).

Used instead of emoji so every icon matches the type and colour of the interface.
"""

_SVG = (
    '<svg class="sp-icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">{paths}</svg>'
)

_PATHS = {
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "shield": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "arrow": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "document": '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "drop": '<path d="M12 3c3.5 4.2 6 7.6 6 10.5A6 6 0 0 1 6 13.5C6 10.6 8.5 7.2 12 3z"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
}


def icon(name: str, size: int = 16) -> str:
    """The SVG markup for icon `name`."""
    return _SVG.format(size=size, paths=_PATHS[name])
