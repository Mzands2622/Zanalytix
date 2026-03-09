import re
import logging

PHASE_SYNONYMS = {
    # ----------------
    # Preclinical
    # ----------------
    "phase 0": "Preclinical",
    "Phase 0": "Preclinical",
    "PHASE 0": "Preclinical",
    "Preclinical": "Preclinical",

    "Pre-Clinical": "Preclinical",
    "Pre-clinical": "Preclinical",
    "preclinical": "Preclinical",

    # ----------------
    # PHASE 1
    # ----------------
    "p1": "Phase 1",
    "pⅰ": "Phase 1",
    "pⅠ": "Phase 1",
    "phase 1": "Phase 1",
    "phase i": "Phase 1",
    "i": "Phase 1",
    "1": "Phase 1",
    "phase – l": "Phase 1",
    "phase - l": "Phase 1",
    "Phase1": "Phase 1",
    "phase1": "Phase 1",

    # ----------------
    # PHASE 2
    # ----------------
    "p2": "Phase 2",
    "pⅱ": "Phase 2",
    "pⅡ": "Phase 2",
    "phase 2": "Phase 2",
    "phase ii": "Phase 2",
    "ii": "Phase 2",
    "2": "Phase 2",
    "phase – ll": "Phase 2",
    "phase - ll": "Phase 2",
    "Phase2": "Phase 2",
    "phase2": "Phase 2",
    

    # ----------------
    # PHASE 3
    # ----------------
    "p3": "Phase 3",
    "pⅲ": "Phase 3",
    "pⅢ": "Phase 3",
    "phase 3": "Phase 3",
    "phase iii": "Phase 3",
    "iii": "Phase 3",
    "3": "Phase 3",
    "phase – lll": "Phase 3",
    "phase - lll": "Phase 3",
    "phase3": "Phase 3",
    "Phase3": "Phase 3",

    # ----------------
    # SUB-PHASES (1a, 1b, etc.)
    # ----------------
    "phase 1a": "Phase 1a",
    "phase i a": "Phase 1a",
    "p1a": "Phase 1a",
    "1a": "Phase 1a",
    "ia": "Phase 1a",
    "Ia": "Phase 1a",

    "p 1 b": "Phase 1b",
    "P 1 b": "Phase 1b",
    "pⅰb": "Phase 1b",
    "pⅠb": "Phase 1b",
    "phase 1b": "Phase 1b",
    "phase i b": "Phase 1b",
    "1b": "Phase 1b",
    "ib": "Phase 1b",
    "Ib": "Phase 1b",

    "phase 2a": "Phase 2a",
    "phase ii a": "Phase 2a",
    "p2a": "Phase 2a",
    "2a": "Phase 2a",
    "iia": "Phase 2a",

    "phase 2b": "Phase 2b",
    "phase ii b": "Phase 2b",
    "p2b": "Phase 2b",
    "2b": "Phase 2b",
    "iib": "Phase 2b",

    "phase 3a": "Phase 3a",
    "phase iii a": "Phase 3a",
    "p3a": "Phase 3a",
    "3a": "Phase 3a",
    "iiia": "Phase 3a",

    # ----------------
    # COMBINED PHASES
    # ----------------
    "piib/iii": "Phase2b/3",
    "pii/iii": "Phase 2/3",
    "pib/ii": "Phase 1b/2",
    "pib/Ii": "Phase 1b/2",
    "pii": "Phase 2",
    "pib": "Phase 1b",
    "piib/Iii": "Phase2b/3",
    "pii/Iii": "Phase2/3",
    "Pib/Ii": "Phase 1b/2",
    "2/Iii": "Phase 2/3",

    # Phase 1/2
    "p1/2": "Phase 1/2",
    "pⅰ/ⅱ": "Phase 1/2",
    "pⅠ/Ⅱ": "Phase 1/2",
    "phase 1/2": "Phase 1/2",
    "phase1/2": "Phase 1/2",
    "Phase1/2": "Phase 1/2",
    "phase i/ii": "Phase 1/2",
    "phase i-ii": "Phase 1/2",
    "1/2": "Phase 1/2",
    "i/ii": "Phase 1/2",

    # Phase 2/3
    "p2/3": "Phase 2/3",
    "pⅱ/ⅲ": "Phase 2/3",
    "pⅡ/Ⅲ": "Phase 2/3",
    "phase 2/3": "Phase 2/3",
    "phase ii/iii": "Phase 2/3",
    "phase ii-iii": "Phase 2/3",
    "2/3": "Phase 2/3",
    "ii/iii": "Phase 2/3",

    # Phase 1b/2
    "p1b/2": "Phase 1b/2",
    "pⅰb/Ⅱ": "Phase 1b/2",
    "pⅰb/ⅱ": "Phase 1b/2",
    "phase 1b/2": "Phase 1b/2",

    # Registration / Review
    "registration": "Registration",
    "r": "Registration",
    "nda filed": "Registration",
    "bla filed": "Registration",
    "under regulatory review": "Under Regulatory Review",
    "under review": "Under Regulatory Review",
    "pre-registration": "Under Regulatory Review",

    # Phase 4 / Post Approval
    "phase 4": "Phase 4",
    "phase iv": "Phase 4",
    "iv": "Phase 4",
    "4": "Phase 4",
    "approved": "Approved",
    "launched": "Approved",
    "commercial": "Approved",
    "marketed": "Approved",

    # Example Non-English or Typos
    "fase 2": "Phase 2",
    "fase 3": "Phase 3",
    "phas 3": "Phase 3",

    # ----------------
    # CUSTOM FALLBACK ENTRIES FROM LOGS
    # ----------------
    # e.g., "pi" => "Phase 1"
    "pi": "Phase 1",
    "piii": "Phase 3",
    # "pi/ii" => "Phase 1/2"
    "pi/ii": "Phase 1/2",
    "Lcm Projects": "LCM Projects",
    "Lcm Project": "LCM Projects",
}


def clean_phase(phase_text):
    """
    Normalize `phase_text` into a canonical Phase form.

    Steps:
      1. Ensure it's a string; convert None or non-strings to str.
      2. Lowercase and strip whitespace.
      3. Unify dash characters (–, —) into '-'.
      4. Replace fancy Roman numerals (Ⅰ, Ⅱ, Ⅲ, ⅰ, ⅱ, ⅲ) with ASCII (i, ii, iii).
      5. Optional regex to unify "phase i" => "phase 1", handle subphases like iia => 2a, etc.
      6. Remove spaces to help dictionary match (e.g., "p ⅰ b" => "pⅰb").
      7. Do dictionary lookup in `PHASE_SYNONYMS`.
      8. If not found, fallback to `.title()`.
      9. Finally, do one more check: if we get something like "Phase2b" or "Phase2/3",
         let's add a space after "Phase" so it becomes "Phase 2b" or "Phase 2/3".
    """

    logging.info(f"[clean_phase] Input => {phase_text}")

    # 1) Convert to string if needed
    if not isinstance(phase_text, str):
        phase_text = str(phase_text or "")
    phase_text = phase_text.lower().strip()

    # 2) Normalize dashes (en-dash, em-dash => hyphen)
    phase_text = phase_text.replace("–", "-").replace("—", "-")

    # 3) Replace fancy Roman numerals (upper & lower) with ASCII
    replacements = {
        "ⅰ": "i",  
        "ⅱ": "ii", 
        "ⅲ": "iii",
        "Ⅰ": "i",  
        "Ⅱ": "ii", 
        "Ⅲ": "iii"
    }
    for fancy, ascii_ in replacements.items():
        phase_text = phase_text.replace(fancy, ascii_)

    # 4) Regex-based replacements
    #    E.g. "phase iii" => "phase 3", "phase ii" => "phase 2", "phase i" => "phase 1"
    phase_text = re.sub(r"\bphase\s*iii\b", "phase 3", phase_text)
    phase_text = re.sub(r"\bphase\s*ii\b",  "phase 2", phase_text)
    phase_text = re.sub(r"\bphase\s*i\b",   "phase 1", phase_text)

    logging.info(f"[clean_phase] Normalized => {phase_text}")

    # 6) Dictionary lookup
    if phase_text in PHASE_SYNONYMS:
        result = PHASE_SYNONYMS[phase_text]
        logging.info(f"[clean_phase] Mapped to => {result}")

        # 9) Final check: insert a space after 'Phase' if there's a digit or slash right after it
        #    e.g. 'Phase2b' => 'Phase 2b', 'Phase2/3' => 'Phase 2/3'
        final = re.sub(r"^(Phase)(\d.*)$", r"Phase \2", result)
        logging.info(f"[clean_phase] Final => {final}")
        return final

    # 7) Fallback (no dictionary match)
    fallback = phase_text.title()
    logging.info(f"[clean_phase] No dictionary match. Fallback => {fallback}")

    # 9) Final check on the fallback
    #    If we have something like 'Phase2b', insert a space => 'Phase 2b'
    final = re.sub(r"^(Phase)(\d.*)$", r"Phase \2", fallback)
    logging.info(f"[clean_phase] Final => {final}")

    return final
