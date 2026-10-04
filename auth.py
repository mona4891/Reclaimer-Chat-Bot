"""Permission checks: owner vs. moderator vs. protected (the server admin)."""

import state
import moderators


def is_owner(player_uid: str) -> bool:
    clean = player_uid.lower().replace("0x", "")
    return clean == state.OWNER_UUID.lower().replace("0x", "") and bool(state.OWNER_PRIVKEY)


def is_mod_or_owner(player_uid: str) -> bool:
    return is_owner(player_uid) or moderators.is_mod(player_uid)


def is_protected(player_uid: str) -> bool:
    return is_owner(player_uid)
