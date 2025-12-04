import logging
from presidio_analyzer import (
    AnalyzerEngine,
    RecognizerRegistry,
    PatternRecognizer,
    Pattern
)
from presidio_anonymizer import AnonymizerEngine, OperatorConfig
from presidio_analyzer.nlp_engine import NlpEngineProvider

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- NLP + Recognizers Setup ----------
# Initialize spaCy NLP engine explicitly
# We use the 'en_core_web_lg' model for better accuracy with named entities.
nlp_configuration = {
    "nlp_engine_name": "spacy",
    "models": [
        {"lang_code": "en", "model_name": "en_core_web_lg"}
    ]
}

try:
    provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
    nlp_engine = provider.create_engine()
except Exception as e:
    logger.warning(f"Failed to initialize Spacy NLP engine: {e}. Ensure 'en_core_web_lg' is installed.")
    # Fallback or re-raise depending on strictness. For now, we'll re-raise as it's critical.
    raise

# ---------- Custom Recognizer Class ----------
class CustomRegexRecognizer(PatternRecognizer):
    """
    A custom recognizer that uses regex patterns to identify entities.
    """
    def __init__(self, entity_name, pattern, score=0.7, name=None):
        """
        Initialize the CustomRegexRecognizer.

        Args:
            entity_name (str): The name of the entity to recognize (e.g., "PDS_WORD").
            pattern (str): The regex pattern to match.
            score (float, optional): The confidence score for matches. Defaults to 0.7.
            name (str, optional): A descriptive name for the recognizer. Defaults to None.
        """
        super().__init__(
            supported_entity=entity_name,
            patterns=[Pattern(name=name or entity_name, regex=pattern, score=score)],
            supported_language='en'
        )

# Initialize registry with predefined recognizers
registry = RecognizerRegistry()
registry.load_predefined_recognizers()

# Add custom recognizers
# PDS Word Recognizer
pds_recognizer = CustomRegexRecognizer(
    'PDS_WORD',
    r'(?i)\bPDS\b',
    score=0.9,
    name='PDS Word Recognizer'
)
registry.add_recognizer(pds_recognizer)

# URL Recognizer
url_recognizer = CustomRegexRecognizer(
    'URL',
    r'https?://[^\s\)\"\',]+',
    score=0.95,
    name='URL Recognizer'
)
registry.add_recognizer(url_recognizer)

# IP Address Recognizer
ip_recognizer = CustomRegexRecognizer(
    'IP_ADDRESS',
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
    score=0.85,
    name='IP Address Recognizer'
)
registry.add_recognizer(ip_recognizer)

# Initialize analyzer engine
analyzer = AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=["en"])

# Initialize anonymizer engine
anonymizer = AnonymizerEngine()

# ---------- Masking Rules ----------
# Define how each entity type should be masked.
operators = {
    "PDS_WORD": OperatorConfig("replace", {"new_value": "<Client_name>"}),
    "URL": OperatorConfig("replace", {"new_value": "<URL>"}),
    "IP_ADDRESS": OperatorConfig("replace", {"new_value": "<IP>"}),
    "PERSON": OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 100, "from_end": False}),
    "EMAIL_ADDRESS": OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 100, "from_end": False}),
    "PHONE_NUMBER": OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 100, "from_end": False}),
}

# Entities to exclude from masking
EXCLUDED_ENTITIES = ["DATE", "DATE_TIME", "US_DRIVER_LICENSE", "ORGANIZATION", "US_PASSPORT"]


def mask_text(text: str) -> str:
    """
    Analyzes and masks PII in the given text string.

    Args:
        text (str): The input text to mask.

    Returns:
        str: The masked text.
    """
    if not text:
        return text
    
    try:
        # Analyze for PII
        analysis_results = analyzer.analyze(text=text, entities=None, language='en')

        # Filter out excluded entities
        filtered_results = [r for r in analysis_results if r.entity_type not in EXCLUDED_ENTITIES]

        # Anonymize text
        anonymized_result = anonymizer.anonymize(
            text=text,
            analyzer_results=filtered_results,
            operators=operators
        )
        return anonymized_result.text
    except Exception as e:
        logger.error(f"Error masking text: {e}")
        return text # Fail safe: return original text or could return "[ERROR MASKING]"

def mask_value(value):
    """
    Recursively masks values in a JSON-like structure (dict, list, str).

    Args:
        value: The value to mask. Can be a string, dict, list, or other types.

    Returns:
        The masked value.
    """
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return mask_json(value)
    if isinstance(value, list):
        return [mask_value(v) for v in value]
    return value

def mask_json(data: dict) -> dict:
    """
    Traverses a dictionary and masks all string values.

    Args:
        data (dict): The dictionary to mask.

    Returns:
        dict: The masked dictionary.
    """
    out = {}
    for k, v in data.items():
        out[k] = mask_value(v)
    return out
