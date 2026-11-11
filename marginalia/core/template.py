"""Tiny mustache-style renderer: {{var}}, {{#var}}shown if truthy{{/var}}, {{^var}}shown if falsy{{/var}}.

Sections are resolved before variables are substituted, so user text is never parsed as template syntax.
"""
from __future__ import annotations

import re

_SECTION = re.compile(r'\{\{([#^])\s*(\w+)\s*\}\}(.*?)\{\{/\s*\2\s*\}\}', re.S)
_VAR = re.compile(r'\{\{\s*(\w+)\s*\}\}')


def render(template: str, ctx: dict) -> str:
    prev = None
    while prev != template:
        prev = template
        template = _SECTION.sub(
            lambda m: m.group(3) if bool(ctx.get(m.group(2))) == (m.group(1) == '#') else '', template)
    return _VAR.sub(lambda m: str(ctx.get(m.group(1), '')), template)
