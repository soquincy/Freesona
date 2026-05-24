# utils/intent.py: Intent evaluation for autonomy decision-making.
# Replaces random.random() with a confidence-scored heuristic pipeline.
# No extra API calls — pure signal scoring on message content and context.

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

# ---------------------------------------------------------------------------
# Intent types
# ---------------------------------------------------------------------------

INTENT_IMAGE_ANALYSIS = "image_analysis"
INTENT_CODE_HELP      = "code_help"
INTENT_GENERAL_CHAT   = "general_chat"
INTENT_IGNORE         = "ignore"

# ---------------------------------------------------------------------------
# Confidence thresholds per frequency setting
# Replaces random.random() < chance
# ---------------------------------------------------------------------------

FREQUENCY_THRESHOLD = {
    "low":     0.70,
    "default": 0.50,
    "high":    0.35,
}

# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

SEMANTIC_TRIGGERS = re.compile(
    r"\b(what|who|why|how|when|where|explain|describe|fix|help|can you|could you|"
    r"tell me|show me|is it|is this|are you|do you|does it|did you|will you|"
    r"should i|what is|what are|what was|what were|what if|think about|"
    r"opinion on|thoughts on|analyze|summarize|translate|write|generate)\b",
    re.IGNORECASE,
)

SHORT_MESSAGE_PATTERN = re.compile(
    r"^(lol|lmao|ok|okay|nice|cool|sure|yeah|yep|nope|no|yes|hmm|hm|"
    r"haha|hehe|omg|wtf|bruh|fr|gg|rip|same|mood|true|facts|based|kek|"
    r"pog|poggers|xd|😂|💀|🔥|👍|👎|😭|😅|🤣)+[.!?]*$",
    re.IGNORECASE,
)

CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]+?```|`[^`]+`")

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IntentResult:
    intent: str
    confidence: float
    requires_response: bool
    targets: list[str] = field(default_factory=list)

    def __str__(self):
        return (
            f"IntentResult(intent={self.intent!r}, "
            f"confidence={self.confidence:.2f}, "
            f"requires_response={self.requires_response}, "
            f"targets={self.targets})"
        )

# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate_intent(
    message: "discord.Message",
    bot_user: "discord.ClientUser | None",
    has_channel_memory: bool = False,
) -> IntentResult:
    """
    Score a message for intent and return an IntentResult.

    Signal weights:
      +0.90  direct mention or reply to bot
      +0.50  supported attachment present
      +0.40  semantic trigger word/phrase
      +0.20  ends with question mark
      +0.10  channel has existing conversation memory
      -0.30  short/filler message (lol, ok, nice, emoji-only)
      -0.20  very long message with no question (monologue, not a prompt)

    Confidence is clamped to [0.0, 1.0].
    """
    content  = message.content or ""
    targets  = []
    score    = 0.0
    intent   = INTENT_GENERAL_CHAT

    # --- Hard ignore: empty message with no attachments ---
    if not content.strip() and not message.attachments:
        return IntentResult(
            intent=INTENT_IGNORE,
            confidence=0.0,
            requires_response=False,
            targets=["empty_message"],
        )

    # --- Signal: direct mention or reply to bot ---
    is_mention = bot_user is not None and bot_user in message.mentions
    is_reply   = (
        bot_user is not None
        and message.reference is not None
        and getattr(message.reference.resolved, "author", None) == bot_user
    )
    if is_mention or is_reply:
        score += 0.90
        targets.append("mention_or_reply")

    # --- Signal: attachment present ---
    if message.attachments:
        score += 0.50
        targets.append("attachment_present")
        # Refine intent based on attachment type
        for att in message.attachments:
            mime = (att.content_type or "").split(";")[0].strip()
            if mime.startswith("image/"):
                intent = INTENT_IMAGE_ANALYSIS
            elif mime.startswith("video/") or mime.startswith("audio/"):
                intent = INTENT_IMAGE_ANALYSIS  # same pipeline, different media
            elif mime in ("application/pdf", "text/plain", "text/markdown"):
                intent = INTENT_GENERAL_CHAT

    # --- Signal: code block present ---
    if CODE_BLOCK_PATTERN.search(content):
        score += 0.40
        targets.append("code_block")
        intent = INTENT_CODE_HELP

    # --- Signal: semantic trigger words ---
    if SEMANTIC_TRIGGERS.search(content):
        score += 0.40
        targets.append("semantic_trigger")

    # --- Signal: ends with question mark ---
    if content.strip().endswith("?"):
        score += 0.20
        targets.append("question_mark")

    # --- Signal: channel has existing memory (bot is part of this conversation) ---
    if has_channel_memory:
        score += 0.10
        targets.append("channel_memory")

    # --- Penalty: short filler message ---
    if SHORT_MESSAGE_PATTERN.match(content.strip()):
        score -= 0.30
        targets.append("short_filler")

    # --- Penalty: long monologue with no question and no mention ---
    if len(content) > 400 and "?" not in content and not is_mention and not is_reply:
        score -= 0.20
        targets.append("long_monologue")

    confidence        = max(0.0, min(1.0, score))
    requires_response = confidence >= 0.50  # default threshold; caller may override

    # Downgrade intent to ignore if confidence is very low
    if confidence < 0.15:
        intent = INTENT_IGNORE

    return IntentResult(
        intent=intent,
        confidence=confidence,
        requires_response=requires_response,
        targets=targets,
    )
