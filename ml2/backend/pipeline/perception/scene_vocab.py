"""Frozen text vocabulary for local scene anchors; no video-specific prompts."""

SCENE_LABELS = {
    "counter_machine": "счётная машинка",
    "safe": "сейф",
    "laptop": "ноутбук",
    "phone": "телефон",
}
SCENE_PROMPTS = {
    "counter_machine": [
        "a photo of a currency counting machine",
        "a photo of a banknote counting machine",
        "a photo of an automatic money counter",
    ],
    "safe": [
        "a photo of a small gray metal cash safe",
        "a photo of an open metal safe cabinet",
        "a photo of a metal security cabinet beside a bank teller desk",
    ],
    "laptop": [
        "a photo of a laptop computer",
        "a photo of an open laptop on a desk",
        "a photo of a notebook computer",
    ],
    "phone": [
        "a photo of a mobile phone",
        "a photo of a smartphone on a desk",
        "a photo of a telephone",
    ],
    "reject_glass": [
        "a photo of a glass partition",
        "a photo of a transparent glass window",
        "a photo of a reflection in glass",
    ],
    "reject_surface": [
        "a photo of a white table",
        "a photo of a desk surface",
        "a photo of an office chair",
    ],
    "reject_other": [
        "a photo of an unidentified object",
        "a photo of an empty counter",
        "a photo of a document on a desk",
    ],
    "reject_bag": [
        "a photo of a handbag",
        "a photo of a suitcase",
        "a photo of a backpack",
    ],
    "reject_monitor": [
        "a photo of a computer monitor",
        "a photo of a television screen",
        "a photo of a display screen",
    ],
}
