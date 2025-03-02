"""Rules and constants for username generation"""

# Character categories
HURUF_RATA = "aceimnorsuvwxz"
HURUF_TIDAK_RATA = "bdfghjklpqty"
HURUF_VOKAL = "aiueo"

# Username types and rules
class UsernameTypes:
    # UNCOMMON Types (Higher Priority)
    class Uncommon:
        OP = "OP"  # On Point - No modification
        SOP = "SOP"  # Semi On Point - Double letters only (e.g., rrabbit, raabbit)
        SCANON = "SCANON"  # Add 'S' suffix (Nomar only) - Same priority as CANON
        CANON = "CANON"  # i/L swap - Same priority as SCANON

    # COMMON Types (Lower Priority)
    class Common:
        TAMHUR = "TAMHUR"  # Add one letter (after CANON/SCANON)
        GANHUR = "GANHUR"  # Replace one letter (lowest priority with SWITCH)
        SWITCH = "SWITCH"  # Adjacent letter swap (lowest priority with GANHUR)
        KURHUF = "KURHUF"  # Remove one letter (lowest priority)

# Name format types
class NameFormat:
    NOMAR = "NOMAR"  # No surname
    WMAR = "WMAR"   # With surname

# Valid username combinations for different categories
VALID_COMBINATIONS = {
    "IDOL_ACTOR_ANIME_GAME_MANHWA": {
        "formats": [NameFormat.NOMAR, NameFormat.WMAR],
        "types": [
            UsernameTypes.Uncommon.OP,
            UsernameTypes.Uncommon.SOP,
            UsernameTypes.Uncommon.CANON,
            UsernameTypes.Uncommon.SCANON,  # Except for WMAR
            UsernameTypes.Common.TAMHUR,
            UsernameTypes.Common.GANHUR,
            UsernameTypes.Common.SWITCH,
            UsernameTypes.Common.KURHUF
        ]
    },
    "MULCHAR": {
        "formats": [NameFormat.NOMAR, NameFormat.WMAR],
        "types": [
            UsernameTypes.Uncommon.OP,
            UsernameTypes.Uncommon.SOP,
            UsernameTypes.Uncommon.CANON,
            UsernameTypes.Common.TAMHUR  # Removed GANHUR from MULCHAR
        ]
    },
    "IDOL_WGROUP_MULCHAR_IMBUHAN_SNS_IDOL": {
        "formats": [NameFormat.NOMAR, NameFormat.WMAR],
        "types": [UsernameTypes.Uncommon.OP]
    },
    "ENGLISH_NAME_IDOL": {
        "formats": [NameFormat.NOMAR, NameFormat.WMAR],  # WMAR only for surname at end
        "types": [
            UsernameTypes.Uncommon.OP,
            UsernameTypes.Uncommon.SOP,
            UsernameTypes.Uncommon.CANON,
            UsernameTypes.Uncommon.SCANON,  # Only for NOMAR
            UsernameTypes.Common.TAMHUR,
            UsernameTypes.Common.GANHUR,
            UsernameTypes.Common.SWITCH,
            UsernameTypes.Common.KURHUF
        ]
    }
}

# Rules for character modifications
MODIFICATION_RULES = {
    "TAMHUR": {
        "TAMPING": "Add one letter at start or end",
        "TAMDAL": "Add one letter in middle"
    },
    "SOP": {
        "rule": "Double existing letters only (e.g., rrabbit, raabbit)",
        "not_allowed": "Single letter additions at edges (use TAMHUR instead)"
    },
    "SCANON": {
        "rule": "Add 'S' at end",
        "restriction": "NOMAR only"
    },
    "CANON": {
        "rule": "Swap 'i' with 'L' or 'L' with 'i'"
    }
}