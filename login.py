from flask import Blueprint, request, jsonify
import hashlib
from db import get_db_connection

# Create a Blueprint for user authentication
login_bp = Blueprint('login', __name__)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@login_bp.route('/login', methods=['POST'])
def login():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        data = request.json
        username = data.get('username')
        password = hash_password(data.get('password'))  # Hash the incoming password

        # Query to check if the username and password match
        cursor.execute("SELECT UserID, Role FROM Users WHERE Username = ? AND Password = ?", (username, password))
        user = cursor.fetchone()

        if user:
            user_id, role = user
            print(f"Login successful for userID: {user_id}, role: {role}")  # Replace logging with print
            return jsonify({"status": "success", "userID": user_id, "role": role}), 200
        else:
            print(f"Invalid login attempt for username: {username}")  # Replace logging with print
            return jsonify({"status": "error", "message": "Invalid username or password."}), 401

    except Exception as e:
        print(f"Error during login: {e}")  # Replace logging with print
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
