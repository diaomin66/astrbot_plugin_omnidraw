"""Select a selfie persona without changing shared plugin configuration."""

import copy
import re
from typing import Any

OUTFIT_PATTERNS = {
    "sleepwear": r"睡衣|连体睡衣|deepsleep|sleepwear|p[ay]jamas?|onesie",
    "sailor": r"水手(?:服|风)?|sailor",
    "workwear": r"工装|工作服|连帽卫衣|hoodie|workwear|cargo\s+(?:pants|jeans)",
    "maid": r"女仆(?:装|服|裙)?|\bmaid\b",
}
ACTIVITY_PATTERNS = {
    "sleepwear": r"睡觉|入睡|睡前|起床|午睡|打哈欠|躺平|deepsleep|\bsleep(?:ing)?\b|bedtime|\bnap\b|waking\s+up",
    "workwear": r"写代码|编程|技术文档|调试|开发|工作|办公|上班|\bcod(?:e|ing)\b|programming|debugging|\bwork(?:ing)?\b",
}
CHIBI_PATTERN = r"q\s*版|q\s*version|\bchibi\b|三头身|大头小身|sd\s*版"
MATURE_PATTERN = r"成熟版|成年比例|正常比例|\bmature\b|adult\s+proportions"


def _positive_text(text: str) -> str:
    """Remove negated routing terms from a selection input.

    Args:
        text: A request, current activity, or outfit description.

    Returns:
        Text whose negated persona and clothing terms cannot trigger a route.
    """
    terms = "|".join(
        [
            *OUTFIT_PATTERNS.values(),
            *ACTIVITY_PATTERNS.values(),
            CHIBI_PATTERN,
            MATURE_PATTERN,
        ]
    )
    return re.sub(
        rf"(?:不要|不用|别|避免|不是|非|不穿|不选|不想|\bnot\b|\bno\b|\bwithout\b|\bavoid\b)\s*(?:穿|用|选|画成|改成|变成|生成|wearing\s+)?(?:{terms})",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    )


def select_selfie_persona(
    settings: dict[str, Any],
    profiles: list[dict[str, Any]],
    active_id: str,
    action: str,
    life_context: dict[str, Any] | None = None,
    wardrobe: list[dict[str, Any]] | None = None,
    persona_id: str = "",
) -> dict[str, Any]:
    """Resolve clothing and body proportions for one image request.

    Args:
        settings: Automatic persona routing configuration.
        profiles: Available persona descriptions and reference image groups.
        active_id: The manual default persona.
        action: The current image request, excluding inherited base prompts.
        life_context: Cached schedule context with the current activity only.
        wardrobe: Available reusable outfit plans.
        persona_id: Optional explicit ID, name, or one-based persona number.

    Returns:
        The chosen persona and a copied life context with matching clothing.

    Raises:
        ValueError: An explicit persona selector is invalid or no personas exist.
    """
    if not profiles:
        raise ValueError("No selfie personas are configured")
    by_id = {str(p["id"]): p for p in profiles}
    default = by_id.get(active_id, profiles[0])
    data = copy.deepcopy(life_context or {})
    request = _positive_text(action)
    explicit = str(persona_id or "").strip()
    selected = None
    outfit_key = ""
    reason = "manual_default"
    outfit_source = ""
    if explicit:
        selected = by_id.get(explicit)
        if selected is None:
            selected = next(
                (p for p in profiles if p.get("persona_name") == explicit), None
            )
        if (
            selected is None
            and explicit.isdigit()
            and 1 <= int(explicit) <= len(profiles)
        ):
            selected = profiles[int(explicit) - 1]
        if selected is None:
            raise ValueError(f"Unknown selfie persona: {explicit}")
        reason = "explicit_persona"
    elif settings.get("enabled", False):
        # The full schedule is deliberately excluded: future sleep entries must
        # not affect a daytime request.
        sources = [
            (request, OUTFIT_PATTERNS, "requested_outfit"),
            (request, ACTIVITY_PATTERNS, "requested_activity"),
            (
                _positive_text(data.get("current_activity", "")),
                ACTIVITY_PATTERNS,
                "current_activity",
            ),
            (_positive_text(data.get("outfit", "")), OUTFIT_PATTERNS, "daily_outfit"),
        ]
        for text, patterns, source in sources:
            outfit_key = next(
                (
                    key
                    for key, pattern in patterns.items()
                    if re.search(pattern, text, re.IGNORECASE)
                ),
                "",
            )
            if outfit_key:
                reason = source
                outfit_source = source
                break
        chibi_id = str(settings.get("chibi_persona_id", ""))
        wants_chibi = bool(re.search(CHIBI_PATTERN, request, re.IGNORECASE))
        wants_mature = bool(re.search(MATURE_PATTERN, request, re.IGNORECASE))
        if wants_chibi or (default["id"] == chibi_id and not wants_mature):
            selected = by_id.get(chibi_id, default)
            reason = "requested_chibi" if wants_chibi else "chibi_manual_default"
        else:
            target_id = (
                str(settings.get(f"{outfit_key}_persona_id", "")) if outfit_key else ""
            )
            selected = by_id.get(target_id)
            if selected is None:
                selected = (
                    by_id.get(str(settings.get("mature_persona_id", "")), default)
                    if wants_mature
                    else default
                )
    selected = selected or default
    if explicit:
        # An explicit profile also fixes its outfit when the mapping is known.
        outfit_key = next(
            (
                key
                for key in OUTFIT_PATTERNS
                if settings.get(f"{key}_persona_id") == selected["id"]
            ),
            "",
        )
    if outfit_key:
        for entry in wardrobe or []:
            description = str(entry.get("description", ""))
            if re.search(
                OUTFIT_PATTERNS[outfit_key], _positive_text(description), re.IGNORECASE
            ):
                data["outfit"] = description
                data["meta"] = {
                    **(data.get("meta") or {}),
                    "style": description.split("；", 1)[0].removeprefix("整体风格："),
                }
                break
    data["selfie_persona"] = str(selected.get("persona_name", selected["id"]))
    return {
        "persona_id": selected["id"],
        "persona_name": str(selected.get("persona_name", selected["id"])),
        "selection_reason": reason,
        "outfit_key": outfit_key,
        "outfit_source": outfit_source,
        "life_context": data,
    }
