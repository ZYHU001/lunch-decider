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
MIN_TAG_MATCH = 0.6

WESTERN_FAST_FOOD_BRANDS = (
    "汉堡王", "麦当劳", "肯德基", "赛百味", "burgerking", "mcdonald", "kfc", "subway",
)


def is_western_fast_food(restaurant):
    """Recognize explicit brands/categories; generic fast food is not enough."""
    name = "".join(str(restaurant.get("name", "")).casefold().split())
    cuisine = "".join(str(restaurant.get("cuisine", "")).casefold().split())
    return (any(brand in name or brand in cuisine for brand in WESTERN_FAST_FOOD_BRANDS)
            or cuisine in {"西式快餐", "洋快餐", "westernfastfood", "americanfastfood"})


NOODLE_SPECIALIST_MARKERS = (
    "面馆", "面食", "拉面", "牛肉面", "刀削面", "热干面", "炸酱面", "油泼面",
    "担担面", "烩面", "板面", "米线", "米粉", "螺蛳粉", "酸辣粉", "土豆粉",
)
RICE_MAIN_MARKERS = ("盖饭", "盖浇饭", "炒饭", "煲仔饭", "咖喱饭", "卤肉饭", "烧肉饭", "拌饭", "饭团", "饭面", "饭与面")


def tag_candidate_allowed(restaurant, field):
    """Apply explicit category conflicts before model judgment, without inventing menus."""
    if field == "variety":
        return not is_western_fast_food(restaurant)
    if field == "rice":
        # Branch/location text and incidental dishes must not redefine a noodle shop.
        name = str(restaurant.get("name", "")).split("(")[0].split("（")[0]
        cuisine = str(restaurant.get("cuisine", ""))
        noodle_specialist = (any(marker in name for marker in NOODLE_SPECIALIST_MARKERS)
                             or cuisine in {"面食", "面馆", "米线", "米粉"})
        explicit_rice_main = any(marker in name or marker in cuisine for marker in RICE_MAIN_MARKERS)
        if noodle_specialist and not explicit_rice_main:
            return False
    return True


TAG_EVIDENCE_RULE = (
    "Judge the restaurant's main, typical lunch identity and signature meals, not whether a matching item could exist somewhere on its menu. "
    "Require explicit supporting evidence in the supplied cuisine, named dishes, or notes for a normal complete lunch matching this tag. "
    "A secondary item, garnish, optional add-on, generic cuisine stereotype, restaurant name alone for preparation/nutrition, or imagined customization is insufficient. "
    "If the primary meal contradicts the tag, or evidence is missing, ambiguous, or only incidental, the match MUST be below 0.6. "
    "A match of 0.6 or above requires a clearly supported primary or signature lunch, not merely a possibility. "
)

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
    'rice': "Is rice the main staple in this restaurant's primary or signature lunch format, such as rice bowls, fried rice, claypot rice, curry rice, or a regular shared-dish lunch explicitly centered on rice? A noodle/rice-noodle specialist does not qualify because of one incidental rice bowl, optional steamed rice, or a possible stir-fry side. Rice noodles, rice vermicelli, rice cakes, and rice flour are not rice meals. A genuinely co-primary rice-and-noodle format needs explicit evidence; do not infer rice simply from a Chinese cuisine category.",
    'noodles': 'Are wheat/flour noodles or dough foods the primary or signature lunch, such as noodles, dumplings, wontons, steamed buns, or flatbreads? A rice restaurant with an incidental noodle option, a hotpot with optional noodles, or a barbecue with a side bread does not qualify. Rice noodles, rice vermicelli, rice cakes and potato/glass noodles do not qualify. Wontons/dumplings must be a substantial main meal, not a small side.',
    'soup': 'Is drinkable soup or broth a substantial, integral part of the primary or signature lunch, such as clearly identified soup noodles, rice-noodle soup, wonton soup, rice in soup, stewed-soup sets, or a soup-based pot intended for drinking? Dry noodles, dry pots, thick sauce, gravy, noodle-shop identity alone, generic hotpot broth used only for cooking, and a small free soup do not qualify. Require explicit soup/broth meal evidence, not an assumption that a restaurant can provide soup.',
    'healthy': "How well do this restaurant's primary or signature complete lunches match a relatively light, lower-oil healthy-style preference? Use these tiers: 0.60-0.70 for ordinary meals with credible evidence of relatively light preparation, such as clear-broth Yunnan rice noodles or clear-broth Chaoshan beef hotpot with boiled beef and vegetables. These may qualify without an explicit low-salt, low-oil or weight-management claim, but MUST NOT receive above 0.70 solely for being clear-broth, boiled or relatively less oily. Reserve 0.80-0.95 for primary complete meals with stronger explicit evidence of low-oil/low-salt preparation, weight-management design, or a well-supported balanced healthy meal; use 0.71-0.79 only with additional supporting healthy preparation evidence beyond an ordinary light meal. This healthy-specific tier policy defines sufficient evidence under the shared tag rules. Do not treat all Yunnan rice noodles or Chaoshan beef hotpots as light: rich/fatty broth, chili oil, oily sauces, fatty cuts or mainly fried sides weaken the match; judge the documented typical preparation and main meal. Do not assume a clear soup is low-salt or that boiled beef has verified low fat. Generic noodles/hotpot, vegetables, lean meat, fish, soup, sushi, an ordinary mixed meal, a marketing name, or a salad side alone do not establish eligibility. If even relatively light preparation is unsupported or the primary meal is oily, fried or rich, the match must be below 0.60. Fried chicken, burgers and fries remain below 0.60 unless a suitable healthy complete lunch is explicitly primary/signature. Do not imagine substitutions, removing sauces or special orders; do not invent nutrition, calorie values, hygiene, food safety or medical benefits.",
    'indulgent': 'Are the primary or signature lunches explicitly rich in fat, fried, cheese/cream-heavy, or otherwise richly hearty for indulgent enjoyment, such as fried chicken, fatty barbecue, cheese pizza, creamy pasta, or oil-rich hotpot? A small fried side, ordinary meal size, meat alone, or chili/salt/sourness alone does not qualify. Lean lightly prepared meat and ordinary noodles/rice do not qualify without evidence of rich preparation. Strong seasoning can support, but cannot replace, evidence of rich food. Do not invent measured calories.',
    'heavy_flavor': 'Do the primary or signature meals have explicit pronounced oil, salt, chili, numbing spice, or concentrated sauce producing strong taste stimulation in an everyday Chinese-food context? Clearly described mala dry pots, heavily seasoned Sichuan/Hunan dishes, or rich oily/sauced stir-fries can qualify. Regional cuisine/name alone, ordinary savory seasoning, a dipping sauce, optional chili, a spicy side, or imagining extra spice does not qualify. Burgers, fried chicken or barbecue are not automatically Chinese-style heavy flavor. Meat and high calories are not required; strong oil/salt/sauce can qualify without chili. There is no separate chili score.',
    'meat': 'Is a substantial portion of livestock or poultry meat the main attraction of the primary or signature lunch, such as chicken pots, barbecue, steak, rib pots, beef stew or roast duck? Fish, shrimp and seafood do not count. Meat broth, minced/shredded meat toppings, an ordinary burger patty, generic beef noodles, or dumpling fillings alone do not establish a meat-centered meal. Rice/noodle/burger meals qualify only with explicit substantial-meat portions that make meat the centerpiece, not merely a meat word in the dish name. Lean meat may qualify independently of indulgence or heavy flavor.',
    'variety': "Is a distinct non-Chinese meal style the primary/signature lunch, such as Japanese sushi or set meals, Korean, Thai, Vietnamese, or non-fast-food Western meals? Ordinary Chinese dishes and familiar regional Chinese cuisines do not qualify because of a novel name or strong taste. One foreign-style side in an otherwise Chinese meal is insufficient. Exclude Western burger/fried-chicken/sandwich fast food including Burger King, McDonald's, KFC, Subway and similar chains: give match 0. Japanese/Korean set meals remain eligible even if served quickly. A fashionable/foreign-sounding shop name alone is insufficient. Do not invent the user's eating history or infer a specific requested cuisine.",
    'quick_meal': 'Is the primary lunch service explicitly a practical complete individual meal, fast-food, ready-to-serve, boxed lunch, choose-your-dishes set, burger set, rice-ball set or simple rice-bowl format? A per-person price, small party capacity, one optional set or the fact that a meal can feed one person does not prove quick-meal service. Shared stir-fry dining, barbecue, hotpot, banquets or multi-course dining are not quick meals just because small portions might exist. Noodle/dumpling shops need evidence of a simple individual meal format, not assumed exact waiting times. Quick meals can be healthy; do not include travel distance or promise a waiting time.',
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
                if field in SEMANTIC_FIELDS:
                    instruction = TAG_EVIDENCE_RULE + instruction
                if field == "party_size_fit":
                    instruction = instruction.format(people=user_prefs["people"])
                questions[question_id] = {"type": "noul", "instructions": f"Evaluate only `{target}` from the state. {instruction} Tags are independent and may overlap; do not force exclusive categories. Base the judgment on its cuisine, dishes, party-size range, and notes. If evidence is insufficient, remain uncertain; do not invent restaurant facts."}
    return questions
