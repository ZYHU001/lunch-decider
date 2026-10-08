"""User-defined lunch ranking weights and deterministic score calculation."""
import math

BASE_WEIGHTS = {"semantic_tag": 1.0, "solo": 1.0, "spiciness": 1.0, "rating": 0.8, "distance": 0.5}
SEMANTIC_FIELDS = ("rice", "noodles", "warm", "clean", "indulgent", "heavy_flavor", "meat", "regional")
TAG_FIELDS = {"米饭": "rice", "面食": "noodles", "热乎的": "warm", "干净的": "clean", "放纵的": "indulgent", "重口的": "heavy_flavor", "吃肉": "meat", "地方菜": "regional"}

def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def rating_to_score(rating):
    rating = finite_number(rating)
    if rating is None:
        return 0.5
    return max(0.0, min(1.0, (rating - 3.5) / 1.2))

def distance_to_score(distance):
    distance = finite_number(distance)
    if distance is None:
        return 0.5
    for limit, score in ((300, 1.0), (600, 0.85), (1000, 0.65), (1500, 0.35), (2000, 0.15)):
        if distance <= limit:
            return score
    return 0.0

def spiciness_match(actual, target):
    actual, target = finite_number(actual), finite_number(target)
    if actual is None or target is None:
        return 0.0
    return max(0.0, 1.0 - abs(actual - target) / 4.0)

def build_weights(user_prefs):
    raw = {field: BASE_WEIGHTS["semantic_tag"] for field in SEMANTIC_FIELDS if user_prefs.get(field)}
    if user_prefs.get("solo"):
        raw["solo_friendly"] = BASE_WEIGHTS["solo"]
    if user_prefs.get("spiciness") is not None:
        raw["spiciness"] = BASE_WEIGHTS["spiciness"]
    raw["rating"] = BASE_WEIGHTS["rating"]
    raw["distance"] = BASE_WEIGHTS["distance"]
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}

def calculate_score(restaurant, jev_scores, user_prefs):
    weights = build_weights(user_prefs)
    values = {field: jev_scores.get(field, 0) for field in (*SEMANTIC_FIELDS, "solo_friendly")}
    values["rating"] = rating_to_score(restaurant.get("rating"))
    values["distance"] = distance_to_score(restaurant.get("distance_m"))
    target = user_prefs.get("spiciness")
    if target is not None:
        values["spiciness"] = spiciness_match(jev_scores.get("spiciness"), target)
    return sum(values[key] * weight for key, weight in weights.items())

NOUl_QUESTIONS = {
    "rice": "Does this restaurant offer rice-based meals as a practical main lunch option?",
    "noodles": "Does this restaurant offer noodles as a practical main lunch option?",
    "warm": "Does this restaurant primarily offer freshly cooked, hot meals suitable for a warm lunch?",
    "clean": "Does this restaurant offer light, fresh, simply prepared meals? Here clean describes the food style, not verified sanitation or food safety.",
    "indulgent": "Does this restaurant offer rich, indulgent comfort food such as fried, fatty, or generously sauced dishes?",
    "heavy_flavor": "Does this restaurant offer strongly seasoned, intensely flavored meals?",
    "meat": "Does this restaurant offer meat-centered meals as a main lunch option?",
    "regional": "Does this restaurant specialize in a recognizable regional cuisine?",
    "solo_friendly": "Is this restaurant suitable for a person eating lunch alone, with individual portions and no need to order shared dishes?",
}

def build_questions(restaurants, user_prefs):
    """Ask only dimensions active in the user's weights; ratings/distances stay local."""
    weights = build_weights(user_prefs)
    questions = {}
    for index, restaurant in enumerate(restaurants):
        target = f"restaurants.r{index}"
        for field in weights:
            question_id = f"r{index}_{field}"
            if field in NOUl_QUESTIONS:
                questions[question_id] = {"type": "noul", "instructions": f"Evaluate only `{target}` from the state. {NOUl_QUESTIONS[field]} Base the judgment on its cuisine, dishes, party-size range, and notes. If evidence is insufficient, remain uncertain; do not invent restaurant facts."}
            elif field == "spiciness":
                questions[question_id] = {"type": "score", "instructions": f"Rate the typical spiciness of `{target}` only. Use its supplied spice value as the primary evidence: 0 means no chili, 1 to 5 mean one to five chili levels. If missing, infer from the described dishes and notes, acknowledging uncertainty.", "criteria": ["0: No chili, not spicy", "1: Very mild, one chili", "2: Mild to medium, two chilies", "3: Spicy, three chilies", "4: Very spicy, four chilies", "5: Extremely spicy, five chilies"]}
    return questions
