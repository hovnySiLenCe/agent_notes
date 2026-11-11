"""Turn a list of annotations into the prompt that gets filled into the agent's input box."""
from __future__ import annotations

from .models import AnnoType, Annotation
from .template import render

FALLBACK_TEMPLATE = '【{{name}}】{{#quote}}「{{quote}}」{{/quote}}{{#comment}}→ {{comment}}{{/comment}}'
# "Plain" fill: just the quote and the user's own words, no header/footer and no per-type instructions.
PLAIN_TEMPLATE = '{{#quote}}「{{quote}}」{{/quote}}{{#comment}} {{comment}}{{/comment}}'


def clean_quote(quote: str, max_chars: int = 0) -> str:
    """Collapse whitespace; elide the middle of long quotes so the agent can still find both ends."""
    q = ' '.join(quote.split())
    if max_chars and len(q) > max_chars:
        head = (max_chars - 1) // 2
        q = q[:head] + '…' + q[len(q) - (max_chars - 1 - head):]
    return q


def compose(items: list[Annotation], types: dict[str, AnnoType], prompt: dict, plain: bool = False) -> str:
    lines = []
    for i, a in enumerate(items, 1):
        t = types.get(a.type_id) or AnnoType(id=a.type_id, name=a.type_id)
        tpl = (prompt.get('plain_template') or PLAIN_TEMPLATE) if plain else (t.template or FALLBACK_TEMPLATE)
        body = render(tpl, {
            'quote': clean_quote(a.quote, int(prompt.get('quote_max_chars', 0) or 0)),
            'comment': a.comment.strip(),
            'name': t.name,
            'index': i,
        }).strip()
        lines.append(body if plain and len(items) == 1 else f'{i}. {body}')
    if plain:
        return '\n'.join(lines)
    parts = [prompt.get('header', '').strip(), '\n'.join(lines), prompt.get('footer', '').strip()]
    return '\n'.join(p for p in parts if p)
