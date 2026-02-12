"""Smart item resolver with fuzzy matching and disambiguation.

Handles ambiguous queries like "T6 Bow" (27 variants) by:
- Loading localization for display names + item metadata for categories
- Parsing tier prefixes (Adept's → T4)
- Parsing shorthand (6.1 → T6@1, 4@3 → T4@3)
- Material/resource prioritization for generic terms
- Item ID complexity scoring (shorter IDs preferred for base materials)
- Alias dictionary for common slang (Paws → 2H_AXE_HELL)
- Phonetic matching for misspellings (Soundex)
- Category context detection from query keywords
- Fuzzy matching with intelligent scoring
- Returning disambiguation options when multiple matches
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import GameDataConfig
from .gamedata import ensure_game_files

logger = logging.getLogger(__name__)

GAME_DATA_DIR = GameDataConfig().dir
LOCALIZATION_FILE = GAME_DATA_DIR / "localization.json"
ITEMS_FILE = GAME_DATA_DIR / "items.json"

# Tier prefix mapping (display name → tier number)
TIER_PREFIXES = {
    "beginner's": 1,
    "novice's": 2,
    "journeyman's": 3,
    "adept's": 4,
    "expert's": 5,
    "master's": 6,
    "grandmaster's": 7,
    "elder's": 8,
}

# Reverse mapping (tier number → prefix)
TIER_TO_PREFIX = {v: k for k, v in TIER_PREFIXES.items()}

# Material keywords that should prioritize raw/refined resources
MATERIAL_KEYWORDS = {
    # Refined resources
    "leather": "LEATHER",
    "cloth": "CLOTH",
    "metal": "METALBAR",
    "metalbar": "METALBAR",
    "bar": "METALBAR",
    "plank": "PLANKS",
    "planks": "PLANKS",
    "wood": "PLANKS",  # Common confusion
    "stone": "STONEBLOCK",
    "stoneblock": "STONEBLOCK",
    "block": "STONEBLOCK",
    # Raw resources
    "hide": "HIDE",
    "fiber": "FIBER",
    "ore": "ORE",
    "log": "WOOD",
    "logs": "WOOD",
    "rock": "ROCK",
}

# Alias dictionary for slang/abbreviations → official item ID patterns
# These patterns match substrings in item IDs (e.g., "2H_DUALAXE_KEEPER" matches T4_2H_DUALAXE_KEEPER)
ITEM_ALIASES = {
    # Artifact weapons (slang names) - based on actual item IDs
    "paws": "2H_DUALAXE_KEEPER",
    "bear paws": "2H_DUALAXE_KEEPER",
    "bearpaws": "2H_DUALAXE_KEEPER",
    "carving": "MAIN_DAGGER",
    "boltcasters": "2H_CROSSBOWLARGE_MORGANA",
    "claws": "MAIN_DAGGERPAIR",
    "bloodletter": "MAIN_DAGGER_MORGANA",
    "deathgivers": "MAIN_DAGGERPAIR_HELL",
    "bridled fury": "2H_AXE_AVALON",
    "halberd": "2H_HALBERD",
    "glaive": "2H_HALBERD_MORGANA",
    "spirithunter": "2H_HALBERD_HELL",
    "realmbreaker": "2H_HAMMER_UNDEAD",
    "grovekeeper": "2H_MACE_KEEPER",
    "camlann": "2H_MACE_AVALON",
    "oathkeepers": "2H_KNUCKLES_AVALON",
    "icicle": "2H_ICEGAUNTLETS_HELL",
    "permafrost": "2H_ICEGAUNTLETS_KEEPER",
    "dawnsong": "2H_ARCANESTAFF_HELL",
    "malevolent locus": "2H_ENIGMATICORB_MORGANA",
    "badon": "2H_BOW_KEEPER",
    "wailing": "2H_BOW_HELL",
    "warbow": "2H_LONGBOW",
    "longbow": "2H_LONGBOW",
    "greataxe": "2H_AXE",
    # Common abbreviations
    "xbow": "2H_CROSSBOW",
    "1h": "MAIN_",  # One-handed
    "2h": "2H_",    # Two-handed
    "oh": "OFF_",   # Off-hand
    # Equipment type shortcuts
    "plate helm": "HEAD_PLATE",
    "cloth helm": "HEAD_CLOTH",
    "leather helm": "HEAD_LEATHER",
}

# Category keywords that indicate what type of item the user wants
CATEGORY_KEYWORDS = {
    # Weapons
    "weapon": "weapon",
    "sword": "weapon",
    "axe": "weapon",
    "mace": "weapon",
    "hammer": "weapon",
    "bow": "weapon",
    "crossbow": "weapon",
    "staff": "weapon",
    "spear": "weapon",
    "dagger": "weapon",
    # Armor
    "armor": "armor",
    "armour": "armor",
    "helm": "armor",
    "helmet": "armor",
    "chest": "armor",
    "jacket": "armor",
    "boots": "armor",
    "shoes": "armor",
    # Offhand
    "offhand": "offhand",
    "off-hand": "offhand",
    "shield": "offhand",
    "torch": "offhand",
    "tome": "offhand",
    "book": "offhand",
    # Accessories
    "cape": "accessory",
    "bag": "accessory",
    "mount": "mount",
    "horse": "mount",
    # Materials (explicit)
    "material": "material",
    "resource": "material",
    "mat": "material",
    "mats": "material",
}

# Shop categories that indicate materials/resources
MATERIAL_CATEGORIES = {"crafting", "resources"}
MATERIAL_SUBCATEGORIES = {"refinedresources", "resources", "rawresources"}


def soundex(word: str) -> str:
    """Generate Soundex code for phonetic matching.

    Soundex converts a word to a 4-character code based on pronunciation.
    Example: "leather" and "lethar" both produce "L360"
    """
    word = word.upper()
    if not word:
        return "0000"

    # Keep first letter
    first = word[0]

    # Soundex mapping
    mapping = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
        'D': '3', 'T': '3',
        'L': '4',
        'M': '5', 'N': '5',
        'R': '6',
    }

    # Convert to codes, skip vowels/H/W/Y
    codes = [first]
    prev_code = mapping.get(first, '0')

    for char in word[1:]:
        code = mapping.get(char, '0')
        if code != '0' and code != prev_code:
            codes.append(code)
            prev_code = code
        elif code == '0':
            prev_code = '0'  # Reset on vowel

    # Pad or truncate to 4 characters
    result = ''.join(codes)[:4]
    return result.ljust(4, '0')


@dataclass
class ResolvedItem:
    """A single resolved item match."""
    unique_name: str
    display_name: str
    tier: int
    enchantment: int = 0
    category: str = ""
    subcategory: str = ""
    score: float = 1.0  # Match confidence (0-1)
    match_reason: str = ""  # Why this matched (for debugging)


@dataclass
class ResolutionResult:
    """Result of item resolution."""
    resolved: bool
    query: str
    matches: list[ResolvedItem] = field(default_factory=list)
    parsed_tier: int | None = None
    parsed_enchantment: int | None = None
    detected_category: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "query": self.query,
            "parsed_tier": self.parsed_tier,
            "parsed_enchantment": self.parsed_enchantment,
            "detected_category": self.detected_category,
            "match_count": len(self.matches),
            "matches": [
                {
                    "unique_name": m.unique_name,
                    "display_name": m.display_name,
                    "tier": m.tier,
                    "enchantment": m.enchantment,
                    "category": m.category,
                    "subcategory": m.subcategory,
                    "score": round(m.score, 3),
                    "match_reason": m.match_reason,
                }
                for m in self.matches[:10]  # Limit to 10
            ],
            "message": self.message,
        }


class SmartItemResolver:
    """Smart item resolver with fuzzy matching and disambiguation.

    Key improvements over basic matching:
    1. Category prioritization - materials get priority for generic terms
    2. Item ID complexity scoring - simpler IDs (T4_LEATHER) beat complex ones (T4_ARMOR_LEATHER_AVALON)
    3. Alias expansion - common slang maps to official IDs
    4. Phonetic matching - Soundex handles misspellings
    5. Context detection - detects if user wants weapon/armor/material
    """

    def __init__(self) -> None:
        self._display_names: dict[str, str] = {}  # item_id → display name
        self._reverse_index: dict[str, str] = {}  # lowercase display → item_id
        self._item_tiers: dict[str, int] = {}  # item_id → tier
        self._item_categories: dict[str, str] = {}  # item_id → shopcategory
        self._item_subcategories: dict[str, str] = {}  # item_id → shopsubcategory1
        self._soundex_index: dict[str, list[str]] = {}  # soundex code → [item_ids]
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load localization and item data if not loaded."""
        if self._loaded:
            return
        self._loaded = True
        ensure_game_files(GAME_DATA_DIR)
        self._load_items_metadata()
        self._load_localization()
        self._build_soundex_index()
        logger.info("[SmartResolver] Loaded %s items", len(self._display_names))

    def _load_items_metadata(self) -> None:
        """Load item metadata (categories) from items.json."""
        if not ITEMS_FILE.exists():
            logger.warning("[SmartResolver] Items file not found: %s", ITEMS_FILE)
            return

        try:
            raw = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[SmartResolver] Failed to load items: %s", exc)
            return

        items_root = raw.get("items", {})

        # Process all item types
        item_types = [
            "simpleitem", "equipmentitem", "weapon", "mount",
            "consumableitem", "furnitureitem", "farmableitem",
            "journalitem", "trackingitem", "trashitem", "killtrophy"
        ]

        for item_type in item_types:
            items = items_root.get(item_type, [])
            if isinstance(items, dict):
                items = [items]

            for item in items:
                if not isinstance(item, dict):
                    continue

                item_id = item.get("@uniquename", "")
                if not item_id:
                    continue

                # Store category metadata
                shop_cat = item.get("@shopcategory", "")
                shop_subcat = item.get("@shopsubcategory1", "")

                if shop_cat:
                    self._item_categories[item_id] = shop_cat
                if shop_subcat:
                    self._item_subcategories[item_id] = shop_subcat

                # Extract tier from item
                tier_str = item.get("@tier", "")
                if tier_str:
                    try:
                        self._item_tiers[item_id] = int(tier_str)
                    except ValueError:
                        pass

    def _load_localization(self) -> None:
        """Load display names from localization.json."""
        if not LOCALIZATION_FILE.exists():
            logger.warning("[SmartResolver] Localization not found: %s", LOCALIZATION_FILE)
            return

        try:
            raw = json.loads(LOCALIZATION_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[SmartResolver] Failed to load localization: %s", exc)
            return

        entries = raw.get("tmx", {}).get("body", {}).get("tu", [])

        for entry in entries:
            tuid = entry.get("@tuid", "")

            # Only process item names (not descriptions)
            if not tuid.startswith("@ITEMS_") or "_DESC" in tuid:
                continue

            # Extract item ID from tuid (e.g., @ITEMS_T6_2H_BOW → T6_2H_BOW)
            item_id = tuid[7:]  # Remove "@ITEMS_" prefix

            # Get English display name
            tuv = entry.get("tuv", {})
            if isinstance(tuv, dict):
                display_name = tuv.get("seg", "")
            elif isinstance(tuv, list):
                display_name = next(
                    (t.get("seg", "") for t in tuv if t.get("@xml:lang") == "EN-US"),
                    ""
                )
            else:
                continue

            if display_name:
                self._display_names[item_id] = display_name
                self._reverse_index[display_name.lower()] = item_id

                # Extract tier from item ID if not already loaded
                if item_id not in self._item_tiers:
                    tier_match = re.match(r"T(\d)", item_id)
                    if tier_match:
                        self._item_tiers[item_id] = int(tier_match.group(1))

    def _build_soundex_index(self) -> None:
        """Build Soundex index for phonetic matching."""
        for item_id, display_name in self._display_names.items():
            # Index each word in the display name
            for word in display_name.split():
                word_clean = re.sub(r"[^a-zA-Z]", "", word)
                if len(word_clean) >= 3:
                    code = soundex(word_clean)
                    if code not in self._soundex_index:
                        self._soundex_index[code] = []
                    if item_id not in self._soundex_index[code]:
                        self._soundex_index[code].append(item_id)

    def parse_query(self, query: str) -> tuple[str, int | None, int | None]:
        """Parse query for tier/enchantment hints.

        Returns (base_query, tier, enchantment)

        Supported formats:
            "T6 Bow" → ("bow", 6, None)
            "T6.2 Bow" → ("bow", 6, 2)
            "6.1 bow" → ("bow", 6, 1)
            "6@3 bow" → ("bow", 6, 3)
            "4.3 bags" → ("bags", 4, 3)
            "4 bow" → ("bow", 4, None)  # Simple numeric tier
            "bow t6" → ("bow", 6, None)  # Reversed format
            "Adept's Broadsword" → ("broadsword", 4, None)
            "Master's Bow of Badon" → ("bow of badon", 6, None)
        """
        query = query.strip()
        tier: int | None = None
        enchant: int | None = None
        base = query.lower()

        # Pattern 1: "T6", "T6.2", "T6@2" prefix
        t_match = re.match(r"t(\d)[\.@]?(\d)?\s*(.+)", base, re.I)
        if t_match:
            tier = int(t_match.group(1))
            if t_match.group(2):
                enchant = int(t_match.group(2))
            base = t_match.group(3).strip()
            return base, tier, enchant

        # Pattern 2: "6.1 item" or "6@3 item" shorthand (with separator)
        num_match = re.match(r"(\d)[\.@](\d)\s+(.+)", base)
        if num_match:
            tier = int(num_match.group(1))
            enchant = int(num_match.group(2))
            base = num_match.group(3).strip()
            return base, tier, enchant

        # Pattern 3: "6 item" simple numeric tier (digit space item)
        simple_num_match = re.match(r"(\d)\s+(.+)", base)
        if simple_num_match:
            tier = int(simple_num_match.group(1))
            base = simple_num_match.group(2).strip()
            return base, tier, enchant

        # Pattern 4: "item t6" or "item T6" reversed format
        reversed_match = re.search(r"\s+t(\d)$", base, re.I)
        if reversed_match:
            tier = int(reversed_match.group(1))
            base = base[:reversed_match.start()].strip()
            return base, tier, enchant

        # Pattern 5: Tier prefix (Adept's, Master's, etc.)
        for prefix, t in TIER_PREFIXES.items():
            if base.startswith(prefix):
                tier = t
                base = base[len(prefix):].strip()
                break

        return base, tier, enchant

    def _detect_category(self, query: str) -> str | None:
        """Detect the intended category from query keywords."""
        query_lower = query.lower()

        # Check for explicit category keywords
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in query_lower:
                return category

        return None

    def _is_material_query(self, base_query: str) -> tuple[bool, str | None]:
        """Check if query is likely asking for a raw/refined material.

        Returns (is_material, material_pattern)
        """
        query_lower = base_query.lower().strip()

        # Check for exact material keyword match
        if query_lower in MATERIAL_KEYWORDS:
            return True, MATERIAL_KEYWORDS[query_lower]

        # Check if query is just a single word that could be a material
        words = query_lower.split()
        if len(words) == 1 and words[0] in MATERIAL_KEYWORDS:
            return True, MATERIAL_KEYWORDS[words[0]]

        return False, None

    def _expand_alias(self, query: str) -> str | None:
        """Expand slang/alias to official item ID pattern."""
        query_lower = query.lower().strip()
        return ITEM_ALIASES.get(query_lower)

    def _item_id_complexity(self, item_id: str) -> int:
        """Calculate item ID complexity (number of parts).

        T4_LEATHER → 2 (simple, likely base material)
        T4_ARMOR_LEATHER_SET1 → 4 (complex, likely equipment)
        """
        # Remove enchantment suffix
        base_id = item_id.split("@")[0]
        return len(base_id.split("_"))

    def _is_material_item(self, item_id: str) -> bool:
        """Check if item is a raw/refined material."""
        cat = self._item_categories.get(item_id, "")
        subcat = self._item_subcategories.get(item_id, "")

        if cat in MATERIAL_CATEGORIES:
            return True
        if subcat in MATERIAL_SUBCATEGORIES:
            return True

        # Also check by ID pattern (backup)
        base_id = item_id.split("@")[0]
        parts = base_id.split("_")
        if len(parts) == 2:
            # Simple format like T4_LEATHER, T4_HIDE
            material_suffixes = {"LEATHER", "CLOTH", "METALBAR", "PLANKS", "STONEBLOCK",
                               "HIDE", "FIBER", "ORE", "WOOD", "ROCK"}
            if parts[1] in material_suffixes:
                return True
            # Also check LEVEL variants like T4_LEATHER_LEVEL1
        elif len(parts) == 3 and "LEVEL" in parts[2]:
            material_suffixes = {"LEATHER", "CLOTH", "METALBAR", "PLANKS", "STONEBLOCK",
                               "HIDE", "FIBER", "ORE", "WOOD", "ROCK"}
            if parts[1] in material_suffixes:
                return True

        return False

    def _fuzzy_score(self, query: str, target: str) -> tuple[float, str]:
        """Calculate fuzzy match score between query and target.

        Returns (score, reason) where reason explains the match type.
        """
        query = query.lower()
        target = target.lower()

        # Exact match
        if query == target:
            return 1.0, "exact"

        # Exact word match (full word boundary)
        query_words = set(query.split())
        target_words = set(target.split())
        if query_words and query_words <= target_words:
            return 0.95, "word_subset"

        # Contains match (but penalize if target is much longer)
        if query in target:
            length_ratio = len(query) / len(target)
            score = 0.85 * length_ratio + 0.1  # Range: 0.1 to 0.95
            return min(0.9, score), "contains"

        # Word overlap (any word matches)
        overlap = query_words & target_words
        if overlap:
            overlap_ratio = len(overlap) / max(len(query_words), len(target_words))
            return 0.6 + (0.2 * overlap_ratio), "word_overlap"

        # Fuzzy sequence match
        seq_score = SequenceMatcher(None, query, target).ratio()
        return seq_score, "sequence"

    def _phonetic_match(self, query: str, limit: int = 20) -> list[str]:
        """Find items matching phonetically using Soundex."""
        matches = []

        for word in query.split():
            word_clean = re.sub(r"[^a-zA-Z]", "", word)
            if len(word_clean) >= 3:
                code = soundex(word_clean)
                if code in self._soundex_index:
                    matches.extend(self._soundex_index[code])

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for item_id in matches:
            if item_id not in seen:
                seen.add(item_id)
                unique.append(item_id)

        return unique[:limit]

    def resolve(self, query: str, limit: int = 10) -> ResolutionResult:
        """Resolve an item query with intelligent matching.

        Args:
            query: User's item query (e.g., "T6 Bow", "T4 leather", "paws")
            limit: Maximum matches to return

        Returns:
            ResolutionResult with matches or disambiguation options
        """
        self._ensure_loaded()

        original_query = query
        base_query, parsed_tier, parsed_enchant = self.parse_query(query)
        detected_category = self._detect_category(query)

        # Check for alias expansion
        alias_pattern = self._expand_alias(base_query)

        # Check if this is a material query
        is_material, material_pattern = self._is_material_query(base_query)

        matches: list[ResolvedItem] = []

        # Strategy 1: Direct alias match
        if alias_pattern:
            for item_id, display_name in self._display_names.items():
                if alias_pattern in item_id:
                    item_tier = self._item_tiers.get(item_id, 0)
                    if parsed_tier is not None and item_tier != parsed_tier:
                        continue

                    enchant = 0
                    if "@" in item_id:
                        try:
                            enchant = int(item_id.split("@")[-1])
                        except ValueError:
                            pass

                    matches.append(ResolvedItem(
                        unique_name=item_id,
                        display_name=display_name,
                        tier=item_tier,
                        enchantment=enchant,
                        category=self._item_categories.get(item_id, ""),
                        subcategory=self._item_subcategories.get(item_id, ""),
                        score=0.98,
                        match_reason="alias",
                    ))

        # Strategy 2: Material-specific matching
        if is_material and material_pattern:
            for item_id, display_name in self._display_names.items():
                # Only match simple material IDs
                if not self._is_material_item(item_id):
                    continue

                # Check if material pattern matches
                if material_pattern not in item_id:
                    continue

                item_tier = self._item_tiers.get(item_id, 0)
                if parsed_tier is not None and item_tier != parsed_tier:
                    continue

                enchant = 0
                if "@" in item_id:
                    try:
                        enchant = int(item_id.split("@")[-1])
                    except ValueError:
                        pass

                # High score for direct material match
                complexity = self._item_id_complexity(item_id)
                complexity_bonus = 0.1 * (5 - complexity) / 5  # Simpler IDs get bonus

                matches.append(ResolvedItem(
                    unique_name=item_id,
                    display_name=display_name,
                    tier=item_tier,
                    enchantment=enchant,
                    category=self._item_categories.get(item_id, ""),
                    subcategory=self._item_subcategories.get(item_id, ""),
                    score=0.95 + complexity_bonus,
                    match_reason="material_keyword",
                ))

        # Strategy 3: Standard fuzzy matching (if we don't have enough material matches)
        if len(matches) < limit:
            for item_id, display_name in self._display_names.items():
                # Skip if already matched
                if any(m.unique_name == item_id for m in matches):
                    continue

                item_tier = self._item_tiers.get(item_id, 0)

                # Filter by tier if specified
                if parsed_tier is not None and item_tier != parsed_tier:
                    continue

                # Calculate match score
                display_lower = display_name.lower()

                # Remove tier prefix from display name for matching
                display_base = display_lower
                for prefix in TIER_PREFIXES.keys():
                    if display_base.startswith(prefix):
                        display_base = display_base[len(prefix):].strip()
                        break

                # Score against display name (without tier prefix)
                display_score, display_reason = self._fuzzy_score(base_query, display_base)

                # Also check against item ID (convert underscores to spaces)
                id_clean = item_id.lower().replace("_", " ")
                # Remove tier prefix from ID
                id_clean = re.sub(r"^t\d\s*", "", id_clean)
                id_score, id_reason = self._fuzzy_score(base_query, id_clean)

                # Use better score
                if id_score > display_score:
                    score = id_score
                    reason = f"id_{id_reason}"
                else:
                    score = display_score
                    reason = f"display_{display_reason}"

                # Apply complexity penalty for equipment when query is generic
                if is_material and not self._is_material_item(item_id):
                    complexity = self._item_id_complexity(item_id)
                    if complexity >= 4:
                        score *= 0.7  # Significant penalty for complex equipment IDs

                # Apply category bonus if detected category matches
                if detected_category:
                    item_cat = self._item_categories.get(item_id, "")
                    if detected_category == "material" and self._is_material_item(item_id):
                        score *= 1.1
                    elif detected_category == "weapon" and item_cat == "weapons":
                        score *= 1.1
                    elif detected_category == "armor" and item_cat in ("armors", "head", "shoes"):
                        score *= 1.1

                if score >= 0.4:  # Minimum threshold
                    # Parse enchantment from item ID
                    enchant = 0
                    if "@" in item_id:
                        try:
                            enchant = int(item_id.split("@")[-1])
                        except ValueError:
                            pass

                    matches.append(ResolvedItem(
                        unique_name=item_id,
                        display_name=display_name,
                        tier=item_tier,
                        enchantment=enchant,
                        category=self._item_categories.get(item_id, ""),
                        subcategory=self._item_subcategories.get(item_id, ""),
                        score=score,
                        match_reason=reason,
                    ))

        # Strategy 4: Phonetic fallback for misspellings
        if len(matches) < 3:
            phonetic_items = self._phonetic_match(base_query)
            for item_id in phonetic_items:
                if any(m.unique_name == item_id for m in matches):
                    continue

                item_tier = self._item_tiers.get(item_id, 0)
                if parsed_tier is not None and item_tier != parsed_tier:
                    continue

                display_name = self._display_names.get(item_id, item_id)

                enchant = 0
                if "@" in item_id:
                    try:
                        enchant = int(item_id.split("@")[-1])
                    except ValueError:
                        pass

                matches.append(ResolvedItem(
                    unique_name=item_id,
                    display_name=display_name,
                    tier=item_tier,
                    enchantment=enchant,
                    category=self._item_categories.get(item_id, ""),
                    subcategory=self._item_subcategories.get(item_id, ""),
                    score=0.5,  # Lower confidence for phonetic matches
                    match_reason="phonetic",
                ))

        # Sort by score (descending), then by tier, then by ID complexity (simpler first)
        matches.sort(key=lambda m: (
            -m.score,
            m.tier,
            self._item_id_complexity(m.unique_name)
        ))

        # Deduplicate by unique_name (keep highest-scoring entry for each ID)
        seen_ids: set[str] = set()
        deduped: list[ResolvedItem] = []
        for m in matches:
            if m.unique_name not in seen_ids:
                seen_ids.add(m.unique_name)
                deduped.append(m)
        matches = deduped[:limit]

        # Determine resolution status
        if len(matches) == 0:
            return ResolutionResult(
                resolved=False,
                query=original_query,
                parsed_tier=parsed_tier,
                parsed_enchantment=parsed_enchant,
                detected_category=detected_category,
                message=f"No items found matching '{original_query}'",
            )

        top_score = matches[0].score

        # Count how many matches have a high score (within 0.1 of top match)
        high_scorers = [m for m in matches if m.score >= top_score - 0.1]

        if len(high_scorers) == 1:
            # Only one clear winner - auto-resolve
            return ResolutionResult(
                resolved=True,
                query=original_query,
                matches=matches[:1],
                parsed_tier=parsed_tier,
                parsed_enchantment=parsed_enchant,
                detected_category=detected_category,
                message=f"Found: {matches[0].display_name}",
            )
        else:
            # Multiple high-scoring matches - need disambiguation
            return ResolutionResult(
                resolved=False,
                query=original_query,
                matches=matches,
                parsed_tier=parsed_tier,
                parsed_enchantment=parsed_enchant,
                detected_category=detected_category,
                message=f"Found {len(high_scorers)} similar matches for '{original_query}'.",
            )

    def get_display_name(self, item_id: str) -> str:
        """Get display name for an item ID."""
        self._ensure_loaded()
        return self._display_names.get(item_id, item_id)


# Default instance
smart_resolver = SmartItemResolver()
