"""User-defined lunch ranking weights and deterministic score calculation."""
import math

# Relative weights, not percentages. Only active dimensions are normalized.
BASE_WEIGHTS = {"semantic_tag": 40, "party_size": 10, "rating": 25, "distance": 15}
TAG_FIELDS = {
    "米饭": "rice", "面食": "noodles", "带汤的": "soup",
    "健康的": "healthy", "放纵的": "indulgent", "重口的": "heavy_flavor",
    "吃肉": "meat", "换个口味": "variety", "快餐": "quick_meal",
}
SEMANTIC_FIELDS = tuple(TAG_FIELDS.values())

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

def build_weights(user_prefs):
    raw = {field: BASE_WEIGHTS["semantic_tag"] for field in SEMANTIC_FIELDS if user_prefs.get(field)}
    raw["party_size_fit"] = BASE_WEIGHTS["party_size"]
    raw["rating"] = BASE_WEIGHTS["rating"]
    raw["distance"] = BASE_WEIGHTS["distance"]
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}

def calculate_score(restaurant, jev_scores, user_prefs):
    weights = build_weights(user_prefs)
    values = {field: jev_scores.get(field, 0) for field in (*SEMANTIC_FIELDS, "party_size_fit")}
    values["rating"] = rating_to_score(restaurant.get("rating"))
    values["distance"] = distance_to_score(restaurant.get("distance_m"))
    return sum(values[key] * weight for key, weight in weights.items())

NOUl_QUESTIONS = {
    "rice": "Does this restaurant offer lunch meals where rice is the main staple, such as rice bowls, fried rice, claypot rice, curry rice, or dishes paired with rice? Merely having optional rice is weak evidence; look for a practical rice-based main meal.",
    "noodles": "Does this restaurant offer lunch meals centered on wheat/flour-based noodles or dough foods, such as noodles, dumplings, wontons, steamed buns, or flatbreads? Small side portions do not strongly match. Rice noodles and rice vermicelli are not included in this tag.",
    "soup": "Does this restaurant offer a practical lunch where drinkable soup or broth is an important part of the meal, or an explicit substantial soup pairing? Examples include noodle soup, rice-noodle soup, wonton soup, rice in soup, stewed-soup sets, and soup pots. Thick sauces, gravy, dry pots, and a small complimentary soup do not strongly match.",
    "healthy": "Does this restaurant offer low-oil, low-salt, weight-management, or balanced healthy-style lunch meals, such as light meals, steamed fish sets, blanched vegetables, or balanced meat-and-vegetable sets? Meat and fish are allowed; this does not require vegetarian food or salad. Vegetables or a marketing label alone are weak evidence. Judge the described meal style, not verified nutrition, medical benefits, hygiene, or food safety; do not invent calorie or nutrient values.",
    "indulgent": "Does this restaurant offer high-calorie, fat-rich, or richly hearty lunch meals for indulgent enjoyment, such as fried chicken, fatty barbecue, cheese pizza, creamy pasta, or oil-rich hotpot? Heavy seasoning may support this tag, but strong chili, salt, or sourness alone does not establish indulgence. Lean or lightly prepared meat is not automatically indulgent. Do not invent measured calorie values.",
    "heavy_flavor": "Does this restaurant offer meals with pronounced rich oil, salt, chili, numbing spice, or heavy sauces, judged in an everyday Chinese-food context? Examples include mala dry pots, heavily seasoned Sichuan/Hunan dishes, and rich stir-fries. Ordinary seasoning or mild savory flavor is weak evidence. This tag does not require meat, high calories, or chili: strongly oily, salty, or sauced non-spicy meals can match. There is no separate chili-level preference or score.",
    "meat": "Does this restaurant offer lunch meals centered on substantial livestock or poultry meat for someone wanting to eat meat as the main attraction, such as chicken pots, barbecue, steak, rib pots, beef stew, or roast duck? Fish, shrimp, and other seafood do not count. Small amounts of shredded/minced meat or meat broth do not strongly match. Rice/noodle meals can match only when abundant meat is genuinely the main attraction. Lean meat can match without being indulgent or heavily seasoned.",
    "variety": "Does this restaurant offer a practical change from everyday Chinese lunch dishes through a distinct non-Chinese meal style, such as Japanese sushi or set meals, Korean, Thai, Vietnamese, or Western food? This is a broad exploration preference, not a request for a specific cuisine. Ordinary Chinese meals, including familiar regional Chinese cuisines, do not strongly match merely because they are spicy or have an unusual dish name. Do not invent the user's eating history.",
    "quick_meal": "Does this restaurant offer practical quick individual lunch meals through fast-food, ready-to-serve, set-meal, or simple-meal formats, such as Chinese fast-food sets, boxed lunches, choose-your-dishes sets, burger sets, rice-ball sets, or simple rice bowls? Long-preparation meals, shared banquets, and lengthy dining formats are weak evidence. Quick meals need not be fried or unhealthy. Use available meal/service-format evidence; do not infer actual waiting times or guaranteed speed, and do not include travel distance in this tag.",
    "party_size_fit": "How well does this restaurant's meal and ordering format suit a lunch party of {people} people? As party size decreases, favor individual portions, fast-food formats, and complete per-person set meals; as party size increases, favor ordering multiple shared dishes, larger portions, and shareable platters or pots. For 1 person, strongly favor a complete individual lunch without having to order several shared dishes; for 2 people, individual sets remain a strong fit while small shareable meals can also fit. For 3-4 people, judge both individual and shared options flexibly; for 5 or more, increasingly favor practical shared dishes or large portions. These are soft preferences, not hard exclusions: a larger group may still fit individual sets, and a small group may fit appropriately sized shared meals. Consider portion format, ordering flexibility, and stated minimum/maximum party sizes. Do not assume a large portion is a banquet or that fast food cannot serve a group. Missing capacity does not prove enough seating; do not invent table sizes, seats, minimum spend, wait times, or portion quantities. Do not repeat travel distance, taste, or calories in this score.",
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
                instruction = NOUl_QUESTIONS[field]
                if field == "party_size_fit":
                    instruction = instruction.format(people=user_prefs["people"])
                questions[question_id] = {"type": "noul", "instructions": f"Evaluate only `{target}` from the state. {instruction} Tags are independent and may overlap; do not force exclusive categories. Base the judgment on its cuisine, dishes, party-size range, and notes. If evidence is insufficient, remain uncertain; do not invent restaurant facts."}
    return questions
