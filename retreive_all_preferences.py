from flask import Blueprint, jsonify
from fetch_preference_options import create_notification_request_object_table
from db import get_db_connection

retreive_options_bp = Blueprint('retreive_options', __name__)

@retreive_options_bp.route('/preferences/<user_id>', methods=['GET'])
def get_user_preferences(user_id):
    conn = get_db_connection()
    create_notification_request_object_table(conn)
    cursor = conn.cursor()

    try:
        # Fetch contact information from ClientContacts table
        cursor.execute("""
            SELECT FirstName, LastName, email, text, call, instagram, facebook
            FROM ClientContacts 
            WHERE UserID = ?
        """, (user_id,))
        contact_info = cursor.fetchone()

        if not contact_info:
            return jsonify({"error": "No contact information found for this user."}), 404

        # This builds a global list of all possible contacts the user has,
        # with 'preferred' initially False:
        all_contacts = []
        for contact_type in ['email', 'text', 'call', 'instagram', 'facebook']:
            raw_val = getattr(contact_info, contact_type)
            if raw_val and raw_val.strip():
                all_contacts.append({
                    "contactType": contact_type,
                    "contactDetail": raw_val.strip(),
                    "preferred": False  # Will flip to True if the row uses it
                })

        # Now fetch all preference sets for the user
        cursor.execute("""
            SELECT *
            FROM Notification_Request_Object_Table
            WHERE UserID = ?
        """, (user_id,))
        all_user_data = cursor.fetchall()

        preference_sets = []

        for user_data in all_user_data:
            preferences_dict = {}
            # This row's "preferred" contacts from columns:
            row_preferred_contacts = []

            column_names = [desc[0] for desc in cursor.description]

            for col_name, col_value in zip(column_names, user_data):
                if col_name == 'SetID':
                    preferences_dict[col_name] = int(col_value) if col_value is not None else None
                elif col_name == 'UserID':
                    preferences_dict[col_name] = int(col_value) if col_value is not None else None
                elif col_name == 'Priority':
                    preferences_dict[col_name] = int(col_value) if col_value is not None else 3
                elif col_name in ['SetTitle', 'FirstName', 'LastName']:
                    preferences_dict[col_name] = col_value  # strings
                elif col_name in ['email', 'text', 'call', 'instagram', 'facebook']:
                    # If the DB row has a non-empty value in e.g. [text],
                    # that means "preferred" contact is `text`.
                    if col_value and str(col_value).strip():
                        row_preferred_contacts.append({
                            "contactType": col_name,
                            "contactDetail": str(col_value).strip(),
                            "preferred": True
                        })
                    # We do NOT directly put these columns into preferences_dict
                    # unless you want to. Typically they remain in the "preferredContacts" array only.
                else:
                    # All the BIT columns for categories/companies/info-types
                    if col_value in (True, 1):
                        preferences_dict[col_name] = True
                    else:
                        preferences_dict[col_name] = False

            # Now unify row_preferred_contacts with the global all_contacts
            # so that if a row used [text], it flips the "preferred" flag to true.
            # But if that contact doesn’t exist in row_preferred_contacts, it stays false, etc.
            merged_contacts = []
            for c in all_contacts:
                # Make a copy so we don't mutate the global object in place
                c_copy = dict(c)  
                # If this global contact also appears in row_preferred_contacts, set preferred = True
                if any(
                    pc["contactType"] == c_copy["contactType"] 
                    and pc["contactDetail"] == c_copy["contactDetail"] 
                    for pc in row_preferred_contacts
                ):
                    c_copy["preferred"] = True
                merged_contacts.append(c_copy)

            # Attach that merged list to the preference set
            preferences_dict['preferredContacts'] = merged_contacts

            preference_sets.append(preferences_dict)

        # Combine contact info plus the preference sets
        full_preferences = {
            "contactInfo": {
                "firstName": contact_info.FirstName,
                "lastName": contact_info.LastName,
            },
            "preferenceSets": preference_sets
        }

        print(full_preferences)
        return jsonify(full_preferences), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@retreive_options_bp.route('/api/user-contact-information/<int:user_id>', methods=['GET'])
def get_user_contact_information(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
        SELECT TOP 1 FirstName, LastName, email, text, call, instagram, facebook
        FROM ClientContacts
        WHERE UserID = ?
        """
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()

        if row:
            contact_info = {
                'firstName': row.FirstName,
                'lastName': row.LastName,
                'email': row.email,
                'text': row.text,
                'call': row.call,
                'instagram': row.instagram,
                'facebook': row.facebook
            }
            # Only include non-null and non-empty string values
            contact_info = {k: v for k, v in contact_info.items() if v and v.strip()}
        else:
            contact_info = None

        cursor.close()
        conn.close()

        print("contact_info", contact_info)
        return jsonify(contact_info), 200
    except Exception as e:
        print(f"Error fetching user contact information: {str(e)}")
        return jsonify({"error": str(e)}), 500
