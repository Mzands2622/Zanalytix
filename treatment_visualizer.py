import json
import traceback
from flask import Blueprint, jsonify, request
from db import get_db_connection

fetch_treatments_bp = Blueprint('fetch_treatments', __name__)

def parse_json_if_needed(value):
    """
    Safely parse a string value to JSON if it looks like JSON.
    Otherwise, return the value as-is (or None).
    """
    if value is None:
        return value
    if isinstance(value, (dict, list)):
        # Already parsed JSON
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        # Check if it starts with { or [ to guess if it's JSON
        if trimmed.startswith('{') or trimmed.startswith('['):
            try:
                return json.loads(trimmed)
            except Exception as e:
                print(f"[DEBUG] JSON parse error in parse_json_if_needed: {e}")
                return trimmed
        else:
            return trimmed
    return value

def extract_first_language_from_obj(value):
    """
    Given a field that might be a string, dict, or array of dicts with "en" keys,
    return a single "en" value or fallback to 'Unknown'.
    """
    if not value:
        return "Unknown"

    # If it's already a simple string
    if isinstance(value, str):
        return value.strip()

    # If it's a dict, try 'en' first, else fallback to the first non-None value
    if isinstance(value, dict):
        if "en" in value:
            en_val = value["en"]
            if en_val is not None:
                return str(en_val).strip()
            else:
                return "Unknown"
        for k, v in value.items():
            if v is not None:
                return str(v).strip()
        return "Unknown"

    # If it's a list, look for a dict with "en"
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and "en" in item:
                en_val = item["en"]
                if en_val is not None:
                    return str(en_val).strip()
                else:
                    return "Unknown"
        # fallback to the first dict's first non-None value
        for item in value:
            if isinstance(item, dict):
                for k, v in item.items():
                    if v is not None:
                        return str(v).strip()
        return "Unknown"

    # If none of the above
    return "Unknown"


@fetch_treatments_bp.route('/api/treatments/search', methods=['GET'])
def get_treatments():
    """
    /api/treatments/search?searchTerm=foo&searchBy=treatment_name&companies=Eisai,Biogen
    Retrieves treatments grouped by phase, optionally filtered by search term and selected companies.
    """
    print("[DEBUG] /api/treatments/search endpoint hit")
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Read query params
    search_term = request.args.get('searchTerm', '').lower()
    search_by = request.args.get('searchBy', 'treatment_name').lower()
    companies = request.args.get('companies', '').split(',')
    companies = [c.strip().lower() for c in companies if c.strip()]

    print(f"[DEBUG] searchTerm='{search_term}', searchBy='{search_by}', companies={companies}")

    try:
        # 2) Fetch all rows from main table
        query = """
        SELECT
            r.Treatment_Key,
            r.Treatment_Data
        FROM Revised_MasterTable r
        """
        print(f"[DEBUG] Executing query: {query.strip()}")
        cursor.execute(query)
        rows = cursor.fetchall()
        print(f"[DEBUG] Retrieved {len(rows)} rows from Revised_MasterTable.")

        treatments_by_phase = {}
        unknown_count = 0

        # 3) Process each row
        for row in rows:
            treatment_key = row[0]
            treatment_data = row[1]

            print(f"[DEBUG] Processing Treatment_Key='{treatment_key}'")

            if not treatment_data:
                print("[DEBUG] treatment_data is empty; skipping row.")
                continue

            # Attempt to parse the JSON array from Treatment_Data
            try:
                treatment_data_list = json.loads(treatment_data)
            except Exception as parse_err:
                print(f"[ERROR] JSON parse error for key='{treatment_key}': {parse_err}")
                continue

            if not treatment_data_list:
                print("[DEBUG] treatment_data_list is empty after JSON parse; skipping row.")
                continue

            # 4) Take the last/most recent snapshot
            most_recent_item = treatment_data_list[-1]
            if not most_recent_item:
                print("[DEBUG] most_recent_item is empty; skipping row.")
                continue

            # 5) Extract the data dict from that item
            try:
                most_recent_data = list(most_recent_item.values())[0]
            except Exception as e:
                print(f"[ERROR] Could not extract most_recent_data for key='{treatment_key}': {e}")
                continue

            # 6) Filter by company
            company_name_json = most_recent_data.get("Company_Name", "Unknown Company")
            company_name_lower = company_name_json.lower()
            if companies and company_name_lower not in companies:
                print(f"[DEBUG] Skipping '{treatment_key}' because '{company_name_lower}' not in selected companies.")
                continue

            # If searching specifically by company_name
            if search_by == 'company_name':
                if search_term and search_term not in company_name_lower:
                    print(f"[DEBUG] Skipping '{treatment_key}' because search_term not in '{company_name_lower}'.")
                    continue

            # 7) Parse out the fields
            raw_phase = most_recent_data.get("Phase", None)
            raw_treatment_name = most_recent_data.get("Treatment_Name", "Unknown Treatment")
            raw_target = most_recent_data.get("Target", "Unknown Target")
            raw_indication = most_recent_data.get("Indication", "Unknown Indication")

            phase_val = extract_first_language_from_obj(parse_json_if_needed(raw_phase)) or ""
            treatment_val = extract_first_language_from_obj(parse_json_if_needed(raw_treatment_name))
            target_val = extract_first_language_from_obj(parse_json_if_needed(raw_target))
            indication_val = extract_first_language_from_obj(parse_json_if_needed(raw_indication))

            english_phase = phase_val.lower() if phase_val else "unknown"

            # 8) Searching logic (if not searching by company_name)
            if search_by != 'company_name':
                search_fields = {
                    'treatment_name': treatment_val.lower(),
                    'target': target_val.lower(),
                    'phase': english_phase,
                    'indication': indication_val.lower(),
                    'company_name': company_name_lower
                }

                if search_term:
                    if search_by == 'phase':
                        # For multi-select phases: "phase 1,phase 2,registration"
                        possible_phases = [ph.strip() for ph in search_term.split(',') if ph.strip()]
                        if english_phase not in possible_phases:
                            print(f"[DEBUG] Skipping '{treatment_key}' because {english_phase} not in {possible_phases}")
                            continue
                    else:
                        # Substring match for name/indication/target
                        if search_term not in search_fields.get(search_by, ''):
                            print(f"[DEBUG] Skipping '{treatment_key}' because '{search_term}' not in {search_by}.")
                            continue

            # 9) Fetch the matching Company_Logo from Profile_Table
            logo_cursor = conn.cursor()
            logo_query = """
                SELECT Company_Logo
                FROM Profile_Table
                WHERE Company_Name = ?
            """
            try:
                logo_cursor.execute(logo_query, (company_name_json,))
                logo_row = logo_cursor.fetchone()
                logo_svg = logo_row[0] if logo_row else None
            except Exception as logo_err:
                print(f"[ERROR] Logo query failed for '{company_name_json}': {logo_err}")
                logo_svg = None
            finally:
                logo_cursor.close()

            # 10) Build the final object
            treatment_info = {
                "treatment_key": treatment_key,
                "treatment_name": treatment_val,
                "company_name": company_name_json,
                "target": target_val,
                "indication": indication_val,
                "phase": english_phase.capitalize(),  # e.g. "Phase 2"
                "logo_svg": logo_svg or ""
            }

            if not english_phase.strip():
                english_phase = "unknown"

            # Track unknown for debugging
            if english_phase == "unknown" or treatment_val.lower() == "unknown":
                unknown_count += 1
                print(f"[DEBUG] Found unknown: Key='{treatment_key}', Phase='{english_phase}', Name='{treatment_val}'")

            phase_key = english_phase.capitalize()  # "Phase 2/3" or "Unknown"
            if phase_key not in treatments_by_phase:
                treatments_by_phase[phase_key] = []
            treatments_by_phase[phase_key].append(treatment_info)

        print(f"[DEBUG] Total 'unknown' treatments in this search: {unknown_count}")
        return jsonify(treatments_by_phase), 200

    except Exception as e:
        print("[ERROR] Exception in get_treatments():")
        print(str(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
        print("[DEBUG] DB connection closed.")


@fetch_treatments_bp.route("/api/treatments/phases", methods=["GET"])
def get_phases_for_companies():
    """
    Gathers all distinct phases by parsing the JSON "Company_Name" field,
    for the companies provided in ?companies=...
    Returns an array of strings, e.g. ["Phase 1", "Phase 2", "Phase 2/3", ...].
    """
    companies_str = request.args.get("companies", "")
    company_list = [c.strip().lower() for c in companies_str.split(",") if c.strip()]

    distinct_phases = set()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if not company_list:
            # No companies -> just return empty list
            return jsonify([]), 200

        # 1) Select ALL rows from the table
        query = "SELECT Treatment_Data FROM Revised_MasterTable"
        cursor.execute(query)
        rows = cursor.fetchall()
        print(f"[DEBUG] get_phases_for_companies -> total rows fetched: {len(rows)}")

        # 2) For each row, parse the JSON array
        for row in rows:
            treatment_data_json = row[0]
            if not treatment_data_json:
                continue

            try:
                treatment_data_list = json.loads(treatment_data_json)
            except Exception as e:
                print(f"[ERROR] JSON parse error in get_phases_for_companies: {e}")
                continue

            if not treatment_data_list:
                continue

            # 3) Grab the last item
            most_recent_item = treatment_data_list[-1]
            if not most_recent_item:
                continue

            # 4) Extract the data object
            try:
                most_recent_data = list(most_recent_item.values())[0]
            except Exception as e:
                print(f"[ERROR] Could not extract most_recent_data in get_phases_for_companies: {e}")
                continue

            # 5) Check if the JSON's company name matches any selected
            company_name_in_json = most_recent_data.get("Company_Name", "Unknown").lower()
            if company_name_in_json not in company_list:
                continue

            # 6) Extract the phase from the JSON
            raw_phase = most_recent_data.get("Phase", None)
            if raw_phase:
                phase_str = extract_first_language_from_obj(parse_json_if_needed(raw_phase))
                if phase_str:
                    distinct_phases.add(phase_str.strip())

    except Exception as e:
        print(f"[ERROR] get_phases_for_companies: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

    # Sort the phases if desired
    sorted_phases = sorted(distinct_phases)
    print(f"[DEBUG] Distinct phases found (JSON-based): {sorted_phases}")
    return jsonify(sorted_phases), 200


@fetch_treatments_bp.route("/api/treatments/<path:treatment_key>/timeline", methods=["GET"])
def get_treatment_timeline(treatment_key):
    """
    Return all historical JSON snapshots for a single treatment_key
    in chronological order. The front-end can display them as a timeline.
    
    Example:
      GET /api/treatments/test_company_CardioHeal_Pro_phase1/timeline
    Returns:
      [
        {
          "snapshotDate": "20250106",
          "snapshotData": { "Company_Name": "...", "Phase": "...", ... }
        },
        ...
      ]
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1) Grab the Treatment_Data for this key
        query = """
            SELECT Treatment_Data
            FROM Revised_MasterTable
            WHERE Treatment_Key = ?
        """
        cursor.execute(query, (treatment_key,))
        row = cursor.fetchone()

        if not row:
            # No row -> return empty
            return jsonify([]), 200

        treatment_data_json = row[0]  # JSON array for all snapshots
        if not treatment_data_json:
            return jsonify([]), 200

        try:
            treatment_data_list = json.loads(treatment_data_json)
        except Exception as e:
            print(f"[ERROR] JSON parse error in get_treatment_timeline: {e}")
            return jsonify({"error": "JSON parse error"}), 500

        if not treatment_data_list:
            return jsonify([]), 200

        # 2) Build a timeline array
        #    Each element looks like {snapshotDate: "YYYYMMDD", snapshotData: {...}}
        timeline = []
        for item in treatment_data_list:
            # Each item looks like {"20250106": {...}}
            (date_key, snapshot_dict) = list(item.items())[0]
            timeline.append({
                "snapshotDate": date_key,
                "snapshotData": snapshot_dict
            })

        # 3) Optionally sort by snapshotDate if it's "YYYYMMDD" numeric
        def parse_yyyymmdd(s):
            return int(s)  # If guaranteed to be 8 digits
        timeline.sort(key=lambda t: parse_yyyymmdd(t["snapshotDate"]))

        return jsonify(timeline), 200

    except Exception as e:
        print("[ERROR] Exception in get_treatment_timeline():", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
        print("[DEBUG] DB connection closed.")
