import re

def clean_text(text):
    """
    Cleans text by:
      1) Normalizing some special quotes and dashes.
      2) Optionally removing or limiting certain punctuation.
      3) Escaping single quotes for naive SQL safety (though parameterized queries are recommended).
    """
    if not isinstance(text, str):
        return text
    
    # Replace common “smart” quotes or dashes with ASCII equivalents
    replacements = {
        '“': '"',
        '”': '"',
        '‘': "'",
        '’': "'",
        '—': '-',
        '–': '-'
    }
    for old_char, new_char in replacements.items():
        text = text.replace(old_char, new_char)

    # If we want to keep more punctuation, let's define a broader whitelist.
    # For example, allow letters, digits, basic punctuation, parentheses, dashes, underscore, plus, etc.
    # Adjust to your needs:
    pattern = r"[^a-zA-Z0-9\(\)\[\]\{\}/\\\-\_\+\=\,\.\:\;\'\"\s<>≤≥]"
    cleaned_text = re.sub(pattern, "", text)

    # Finally, if we still want to double up single quotes for naive SQL safety:
    cleaned_text = cleaned_text.replace("'", "''")

    # Trim whitespace
    cleaned_text = cleaned_text.strip()

    return cleaned_text
