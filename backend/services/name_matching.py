"""Centralised player name matching across data sources.

Handles:
- Unicode accent normalization (Ureña → Urena, José → Jose)
- Known nickname/alternate spelling aliases
- Suffix stripping (Jr., Sr., II, III, IV)
- First initial + last name fuzzy matching
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

# ── Known aliases: canonical name → set of alternate spellings ────────────
# The canonical name should match the SaberSim CSV "Name" column.
# Add entries here when a mismatch is discovered.
_ALIASES: Dict[str, list[str]] = {
    # Accent / transliteration variants
    "Walber Urena": ["Wálber Ureña", "Walbert Urena"],
    "Yainer Diaz": ["Yainer Díaz"],
    "Luis Garcia": ["Luis García"],
    "Jose Abreu": ["José Abreu"],
    "Jose Altuve": ["José Altuve"],
    "Jose Ramirez": ["José Ramírez", "Jose Ramírez"],
    "Jose Berrios": ["José Berríos", "José Berrios"],
    "Jose Leclerc": ["José Leclerc"],
    "Jose Quintana": ["José Quintana"],
    "Luis Arraez": ["Luis Arráez"],
    "Luis Castillo": ["Luis Castillo"],
    "Edwin Diaz": ["Edwin Díaz"],
    "Nestor Cortes": ["Néstor Cortés", "Nestor Cortés", "Néstor Cortes"],
    "Carlos Correa": ["Carlos Correa"],
    "Adolis Garcia": ["Adolis García"],
    "Andres Gimenez": ["Andrés Giménez", "Andres Giménez"],
    "German Marquez": ["Germán Márquez", "German Márquez"],
    "Pablo Lopez": ["Pablo López"],
    "Jorge Lopez": ["Jorge López"],
    "Cristian Javier": ["Cristian Javier"],
    "Christian Vazquez": ["Christian Vázquez"],
    "Eugenio Suarez": ["Eugenio Suárez"],
    "Ronald Acuna Jr": ["Ronald Acuña Jr", "Ronald Acuña Jr.", "Ronald Acuna"],
    "Vladimir Guerrero Jr": ["Vladimir Guerrero Jr.", "Vladimir Guerrero"],
    "Fernando Tatis Jr": ["Fernando Tatís Jr", "Fernando Tatís Jr.", "Fernando Tatis"],
    "Wander Franco": ["Wander Franco"],
    "Yandy Diaz": ["Yandy Díaz"],
    "Julio Rodriguez": ["Julio Rodríguez"],
    "Eloy Jimenez": ["Eloy Jiménez"],
    "Gleyber Torres": ["Gleyber Torres"],
    "Framber Valdez": ["Framber Valdez"],
    "Ranger Suarez": ["Ranger Suárez"],
    "Yordan Alvarez": ["Yordan Álvarez"],
    "Alex Verdugo": ["Alex Verdugo"],
    "Sandy Alcantara": ["Sandy Alcántara"],
    "Jazz Chisholm Jr": ["Jazz Chisholm Jr.", "Jazz Chisholm"],
    "Lourdes Gurriel Jr": ["Lourdes Gurriel Jr.", "Lourdes Gurriel"],
    "Willy Adames": ["Willy Adames"],
    "Xander Bogaerts": ["Xander Bogaerts"],
    "Oscar Gonzalez": ["Óscar González", "Oscar González"],
    "Yadier Molina": ["Yadier Molina"],
    "Luis Robert Jr": ["Luis Robert Jr.", "Luis Robert"],
    "Jo Adell": ["Jo Adell"],
    "CJ Abrams": ["C.J. Abrams", "CJ Abrams"],
    "AJ Minter": ["A.J. Minter"],
    "TJ Friedl": ["T.J. Friedl", "TJ Friedl"],
    "JP Crawford": ["J.P. Crawford", "JP Crawford"],
    "JD Martinez": ["J.D. Martinez", "J.D. Martínez"],
    "JT Realmuto": ["J.T. Realmuto"],
    "MJ Melendez": ["M.J. Melendez", "MJ Meléndez"],
    "Ha-Seong Kim": ["Ha-seong Kim", "Ha Seong Kim"],
    "Hyun Jin Ryu": ["Hyun-Jin Ryu", "Hyun-jin Ryu"],
    "Shohei Ohtani": ["Shohei Ohtani"],
    "Yoshinobu Yamamoto": ["Yoshinobu Yamamoto"],
    "Yu Darvish": ["Yu Darvish"],
    "Seiya Suzuki": ["Seiya Suzuki"],
    "Shota Imanaga": ["Shōta Imanaga", "Shota Imanaga"],
    # Common DK vs SaberSim differences
    "Giancarlo Stanton": ["Giancarlo Stanton"],
    "Mike Trout": ["Michael Trout"],
    "Mike Yastrzemski": ["Michael Yastrzemski"],
    "Zach Eflin": ["Zachary Eflin", "Zac Eflin"],
    "Zach Wheeler": ["Zachary Wheeler"],
    "Matt Olson": ["Matthew Olson"],
    "Matt Chapman": ["Matthew Chapman"],
    "Chris Sale": ["Christopher Sale"],
    "Nick Castellanos": ["Nicholas Castellanos"],
    "Bobby Witt Jr": ["Bobby Witt Jr.", "Bobby Witt"],
    "Manny Machado": ["Manuel Machado"],
}

# Build reverse lookup: normalised alternate → normalised canonical
_REVERSE_ALIAS: Dict[str, str] = {}


def _strip_accents(s: str) -> str:
    """Remove diacritical marks / accents from a string.

    'Ureña' → 'Urena', 'José' → 'Jose'
    """
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _normalise(name: str) -> str:
    """Normalise a player name for matching.

    Steps:
    1. Strip accents
    2. Remove suffixes (Jr., Sr., II, III, IV)
    3. Remove periods, normalise hyphens to spaces
    4. Collapse whitespace, lowercase
    """
    name = _strip_accents(name.strip())
    # Remove common suffixes
    name = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV)\s*$", "", name, flags=re.IGNORECASE)
    # Remove periods, normalise hyphens
    name = name.replace(".", "").replace("-", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name.lower()


def _build_reverse_aliases() -> None:
    """Build the reverse alias mapping on first use."""
    if _REVERSE_ALIAS:
        return
    for canonical, alts in _ALIASES.items():
        norm_canonical = _normalise(canonical)
        _REVERSE_ALIAS[norm_canonical] = norm_canonical
        for alt in alts:
            norm_alt = _normalise(alt)
            if norm_alt != norm_canonical:
                _REVERSE_ALIAS[norm_alt] = norm_canonical


def canonical_name(name: str) -> str:
    """Return the canonical (normalised) form of a player name.

    Uses the alias table first, then falls back to plain normalisation.
    """
    _build_reverse_aliases()
    norm = _normalise(name)
    return _REVERSE_ALIAS.get(norm, norm)


def names_match(name1: str, name2: str) -> bool:
    """Check whether two player names refer to the same person.

    Uses:
    1. Canonical alias lookup
    2. Exact normalised match
    3. Last-name + first-initial fuzzy match
    """
    c1 = canonical_name(name1)
    c2 = canonical_name(name2)

    if c1 == c2:
        return True

    # Fuzzy: same last name + same first initial
    parts1 = c1.split()
    parts2 = c2.split()
    if parts1 and parts2 and parts1[-1] == parts2[-1]:
        if len(parts1) > 1 and len(parts2) > 1:
            if parts1[0][0] == parts2[0][0]:
                return True

    return False


def find_in_dict(name: str, name_dict: Dict[str, Any]) -> Optional[Tuple[str, Any]]:
    """Find a player name in a dictionary using canonical matching.

    Returns (matched_key, value) or None.
    Tries canonical lookup first (O(1)), then falls back to fuzzy scan.
    """
    _build_reverse_aliases()
    target = canonical_name(name)

    # Build canonical → original key mapping on first use per dict
    # (this is cheap for dicts of ~200 players)
    for dict_name, value in name_dict.items():
        if canonical_name(dict_name) == target:
            return (dict_name, value)

    # Fuzzy fallback: last name + first initial
    parts_target = target.split()
    if not parts_target:
        return None

    for dict_name, value in name_dict.items():
        cn = canonical_name(dict_name)
        parts_cn = cn.split()
        if parts_cn and parts_cn[-1] == parts_target[-1]:
            if len(parts_cn) > 1 and len(parts_target) > 1:
                if parts_cn[0][0] == parts_target[0][0]:
                    return (dict_name, value)

    return None


def build_canonical_lookup(name_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Build a lookup dict keyed by canonical name for O(1) access.

    If two entries map to the same canonical name, the last one wins.
    """
    _build_reverse_aliases()
    result: Dict[str, Any] = {}
    for name, value in name_dict.items():
        result[canonical_name(name)] = value
    return result
