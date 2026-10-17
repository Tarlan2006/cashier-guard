"""Shared, camera-independent prompt groups for anchors and observable states."""

from .scene_vocab import SCENE_PROMPTS

PROMPT_GROUPS = {f"anchor.{name}": phrases for name, phrases in SCENE_PROMPTS.items()}
PROMPT_GROUPS["anchor.safe"] = [
    "a gray metal safe cabinet with a rectangular door",
    "a small metal cash safe beside a bank counter",
    "a gray security cabinet against a wall",
]
PROMPT_GROUPS.update(
    {
        "table.items": [
            "banknotes lying on a bank counter",
            "papers and loose objects lying on a desk",
            "an unattended bag lying on a table",
        ],
        "table.empty": [
            "an empty tabletop without loose objects",
            "a clean bank counter without money or papers",
            "an empty desk surface",
        ],
        "table.held": [
            "money held in a person's hands",
            "a person holding papers above a counter",
            "a person holding a bag",
        ],
        "table.unknown": [
            "a person's clothing covering the view",
            "a chair or the floor",
            "a table obscured by a person's body",
        ],
        "safe.open": [
            "a metal safe with its door open",
            "an open gray safe showing its dark interior",
            "an open safe door beside a cabinet",
        ],
        "safe.closed": [
            "a metal safe with its door closed",
            "a closed gray safe cabinet",
            "the front of a closed safe",
        ],
        "safe.unknown": [
            "a glass partition or window",
            "a computer monitor",
            "a cabinet whose door is obscured",
        ],
        "laptop.unlocked": [
            "a laptop screen displaying application windows",
            "a computer desktop with an open program",
            "an active laptop workspace",
        ],
        "laptop.locked": [
            "a laptop screen showing a login form",
            "a computer screen asking for a password",
            "the lock screen of a laptop",
        ],
        "laptop.unknown": [
            "a dark or unreadable computer screen",
            "a closed laptop lid",
            "glare obscuring a computer screen",
        ],
    }
)
