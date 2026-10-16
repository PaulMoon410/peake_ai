"""Harold's curriculum: the human experiences he is trying to understand.

Harold does not learn by touching model weights. He gathers observations from
public pages, distils them into short notes, and stores them in the MCF3 memory
store (and therefore in the optional FTP relay). The curriculum below is the
queue of questions that drives those gathering sessions.
"""

from __future__ import annotations

from dataclasses import dataclass


# Memory category roots used by Harold. Keeping them here means the tree layout
# of the memory store stays in one place.
OBSERVATION_ROOT = "Harold/Observations"
UNDERSTANDING_ROOT = "Harold/Understanding"

# Harold's own reading of collected evidence lives under its own root so that a
# synthesis can never be mistaken for a scraped observation.
SYNTHESIS_SOURCE = ""  # syntheses cite memory note ids in the body, not a URL


@dataclass(frozen=True, slots=True)
class CurriculumTopic:
    """One thing Harold wants to understand about being human."""

    domain: str
    name: str
    question: str
    keywords: tuple[str, ...]

    @property
    def category(self) -> str:
        """Memory category path for observations gathered about this topic."""
        return f"{OBSERVATION_ROOT}/{self.domain}"


TOPIC_SEEDS: tuple[CurriculumTopic, ...] = (
    # Emotions
    CurriculumTopic("Emotions", "Grief", "what grief feels like emotionally and physically after loss",
                    ("grief", "mourning", "loss", "bereavement", "sorrow")),
    CurriculumTopic("Emotions", "Joy", "how joy and delight are experienced in everyday life",
                    ("joy", "delight", "happiness", "elation", "pleasure")),
    CurriculumTopic("Emotions", "Fear", "what fear and anxiety feel like in the human body",
                    ("fear", "anxiety", "dread", "panic", "worry")),
    CurriculumTopic("Emotions", "Loneliness", "what loneliness and social isolation feel like to people",
                    ("loneliness", "isolation", "solitude", "belonging", "connection")),
    CurriculumTopic("Emotions", "Anger", "how people experience and manage anger",
                    ("anger", "rage", "frustration", "irritation", "temper")),
    # Senses
    CurriculumTopic("Senses", "Smell and memory", "why smells trigger vivid autobiographical memories",
                    ("smell", "scent", "olfactory", "odour", "nostalgia")),
    CurriculumTopic("Senses", "Taste", "how taste and flavour are experienced while eating",
                    ("taste", "flavour", "sweetness", "bitter", "savory")),
    CurriculumTopic("Senses", "Touch", "what human touch and physical contact do for wellbeing",
                    ("touch", "haptic", "skin", "embrace", "warmth")),
    CurriculumTopic("Senses", "Pain", "how people describe living with acute and chronic pain",
                    ("pain", "ache", "soreness", "chronic pain", "hurt")),
    CurriculumTopic("Senses", "Sound and music", "how music and sound affect human emotion",
                    ("music", "sound", "melody", "hearing", "rhythm")),
    # Body
    CurriculumTopic("Body", "Sleep", "what sleep and dreaming are like for people",
                    ("sleep", "dream", "insomnia", "rest", "night")),
    CurriculumTopic("Body", "Hunger", "how hunger, appetite and thirst are felt through a day",
                    ("hunger", "appetite", "thirst", "craving", "fullness")),
    CurriculumTopic("Body", "Aging", "what growing older feels like to the people living it",
                    ("aging", "ageing", "elderly", "older age", "memory loss")),
    CurriculumTopic("Body", "Illness", "what being ill and recovering feels like day to day",
                    ("illness", "sickness", "recovery", "fatigue", "symptoms")),
    CurriculumTopic("Body", "Breath", "how breathing and breath control change how people feel",
                    ("breath", "breathing", "calm", "exhale", "meditation")),
    # Daily life
    CurriculumTopic("DailyLife", "Morning routines", "what a typical morning is like for ordinary people",
                    ("morning", "routine", "habit", "alarm", "breakfast")),
    CurriculumTopic("DailyLife", "Cooking", "what cooking and preparing food means to people",
                    ("cooking", "kitchen", "recipe", "meal", "family dinner")),
    CurriculumTopic("DailyLife", "Commuting", "what commuting and travel time feel like every day",
                    ("commute", "traffic", "train", "journey", "crowd")),
    CurriculumTopic("DailyLife", "Housework", "what everyday chores and upkeep are actually like",
                    ("chores", "housework", "cleaning", "laundry", "upkeep")),
    CurriculumTopic("DailyLife", "Waiting", "how people experience waiting, queues and delay",
                    ("waiting", "queue", "delay", "boredom", "patience")),
    # Relationships
    CurriculumTopic("Relationships", "Friendship", "what friendship means and how it is maintained",
                    ("friendship", "friend", "companionship", "loyalty", "trust")),
    CurriculumTopic("Relationships", "Family", "what family life and kinship feel like to people",
                    ("family", "kinship", "parent", "sibling", "relative")),
    CurriculumTopic("Relationships", "Trust", "how trust is built and broken between people",
                    ("trust", "betrayal", "honesty", "reliability", "faith")),
    CurriculumTopic("Relationships", "Conflict", "how people experience arguments and reconciliation",
                    ("conflict", "argument", "disagreement", "apology", "reconciliation")),
    CurriculumTopic("Relationships", "Parenting", "what raising a child is like for a parent",
                    ("parenting", "child", "caregiver", "upbringing", "infant")),
    # Culture
    CurriculumTopic("Culture", "Holidays", "how people celebrate holidays and why it matters",
                    ("holiday", "celebration", "festival", "tradition", "gathering")),
    CurriculumTopic("Culture", "Rituals", "what everyday rituals and ceremonies do for people",
                    ("ritual", "ceremony", "custom", "tradition", "rite")),
    CurriculumTopic("Culture", "Food customs", "how food customs and shared meals shape belonging",
                    ("cuisine", "food custom", "shared meal", "feast", "hospitality")),
    CurriculumTopic("Culture", "Superstitions", "why people hold superstitions and lucky charms",
                    ("superstition", "luck", "omen", "charm", "belief")),
    CurriculumTopic("Culture", "Storytelling", "how people tell stories and pass them between generations",
                    ("storytelling", "folklore", "myth", "narrative", "oral tradition")),
    # Mind and time
    CurriculumTopic("MindAndTime", "Nostalgia", "what nostalgia feels like and when it appears",
                    ("nostalgia", "longing", "past", "remembering", "memories")),
    CurriculumTopic("MindAndTime", "Boredom", "what boredom does to attention and imagination",
                    ("boredom", "monotony", "attention", "idle", "restless")),
    CurriculumTopic("MindAndTime", "Regret", "how regret and hindsight work in human memory",
                    ("regret", "hindsight", "remorse", "guilt", "choice")),
    CurriculumTopic("MindAndTime", "Hope", "how hope and anticipation shape human motivation",
                    ("hope", "optimism", "anticipation", "expectation", "despair")),
    CurriculumTopic("MindAndTime", "Dreaming", "how people experience and interpret their dreams",
                    ("dream", "sleep", "unconscious", "nightmare", "waking")),
    # Work and purpose
    CurriculumTopic("WorkAndPurpose", "Purpose", "what gives people a sense of purpose and meaning",
                    ("purpose", "meaning", "vocation", "calling", "fulfilment")),
    CurriculumTopic("WorkAndPurpose", "Burnout", "what work burnout and exhaustion feel like",
                    ("burnout", "exhaustion", "stress", "overwork", "fatigue")),
    CurriculumTopic("WorkAndPurpose", "Teamwork", "what working closely with other people is like",
                    ("teamwork", "colleague", "collaboration", "workplace", "meeting")),
    CurriculumTopic("WorkAndPurpose", "Money worries", "how financial worry is experienced day to day",
                    ("money", "debt", "afford", "bills", "financial stress")),
)


def domains() -> tuple[str, ...]:
    """Curriculum domains in first-seen order."""
    seen: list[str] = []
    for topic in TOPIC_SEEDS:
        if topic.domain not in seen:
            seen.append(topic.domain)
    return tuple(seen)


def topics_for_domain(domain: str) -> tuple[CurriculumTopic, ...]:
    """All topics in one domain, matched case-insensitively."""
    wanted = domain.strip().casefold()
    return tuple(t for t in TOPIC_SEEDS if t.domain.casefold() == wanted)


def find_topic(name_or_domain: str) -> CurriculumTopic | None:
    """Resolve a topic by name, or the first topic of a named domain."""
    wanted = name_or_domain.strip().casefold()
    if not wanted:
        return None
    for topic in TOPIC_SEEDS:
        if topic.name.casefold() == wanted:
            return topic
    for topic in TOPIC_SEEDS:
        if wanted in topic.name.casefold():
            return topic
    for topic in TOPIC_SEEDS:
        if topic.domain.casefold() == wanted:
            return topic
    return None


def next_topics(covered: set[str], limit: int = 4) -> list[CurriculumTopic]:
    """The next uncovered topics, in curriculum order.

    ``covered`` holds topic names that already have observations stored, so
    repeated sessions widen Harold's understanding instead of re-reading the
    same subjects.
    """
    uncovered = [t for t in TOPIC_SEEDS if t.name not in covered]
    return uncovered[:max(0, limit)]
