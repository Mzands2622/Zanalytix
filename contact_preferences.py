from flask import Blueprint, request, jsonify, session  # Add session if you use it for user management
import logging
from db import get_db_connection

# Create a Blueprint for the contact preferences
contact_preferences_bp = Blueprint('contact_preferences', __name__)

@contact_preferences_bp.route('/save-or-update-contact-preference', methods=['POST'])
def save_or_update_contact_preference():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        data = request.json
        print(data)
        user_id = data.get('userID')  # Assuming userID is sent in the request body
        
        # Ensure user_id is provided
        if not user_id:
            return jsonify({"status": "error", "message": "UserID is required"}), 400
        
        first_name = data.get('firstName')
        last_name = data.get('lastName')

        # Initialize all contact detail fields as None
        email = None
        text_number = None
        call_number = None
        instagram = None
        facebook = None

        # Extract contact details from the contacts array
        for contact in data.get('contacts', []):
            if contact['type'] == 'email':
                email = contact['detail']
            elif contact['type'] == 'text':
                text_number = contact['detail']
            elif contact['type'] == 'call':
                call_number = contact['detail']
            elif contact['type'] == 'instagram':
                instagram = contact['detail']
            elif contact['type'] == 'facebook':
                facebook = contact['detail']

        # Check if the contact already exists for this user
        cursor.execute("SELECT ClientID FROM ClientContacts WHERE UserID = ?", (user_id,))
        existing_contact = cursor.fetchone()

        if existing_contact:
            # Update existing contact and get ClientID
            client_id = existing_contact[0]
            query = """
            UPDATE ClientContacts SET email = ?, text = ?, call = ?, instagram = ?, facebook = ?
            WHERE ClientID = ?
            """
            cursor.execute(query, (email, text_number, call_number, instagram, facebook, client_id))
            message = "Contact preference updated successfully."
        else:
            # Insert new contact
            query = """
            INSERT INTO ClientContacts (UserID, FirstName, LastName, email, text, call, instagram, facebook)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """
            cursor.execute(query, (user_id, first_name, last_name, email, text_number, call_number, instagram, facebook))
            conn.commit()

            # Retrieve the new ClientID
            cursor.execute("SELECT SCOPE_IDENTITY();")
            client_id = cursor.fetchval()  # Get the last inserted ClientID
            message = "Contact preference added successfully."

        conn.commit()
        return jsonify({"status": "success", "message": message, "clientID": client_id}), 200
    except Exception as e:
        logging.error(f"Error saving or updating contact preference: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
