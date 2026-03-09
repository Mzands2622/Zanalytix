from flask import Blueprint, request, jsonify
from datetime import datetime
from db import get_db_connection

# Define the blueprint
scripts_bp = Blueprint('scripts', __name__)

# Route to fetch the latest script for a specific company
@scripts_bp.route('/scripts/<int:company_id>', methods=['GET'])
def get_script(company_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT TOP 1 ScriptText, LastModifiedBy, Timestamp
            FROM Scripts
            WHERE Company_ID = ?
            ORDER BY Timestamp DESC;
        """
        cursor.execute(query, (company_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return jsonify({
                "scriptText": result[0],
                "lastModifiedBy": result[1],
                "timestamp": result[2].strftime('%Y-%m-%d %H:%M:%S')
            }), 200
        else:
            # Return empty script instead of 404
            return jsonify({
                "scriptText": "",
                "lastModifiedBy": None,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to save an updated script for a specific company
@scripts_bp.route('/scripts/<int:company_id>', methods=['POST'])
def save_script(company_id):
    try:
        data = request.json
        script_text = data.get('scriptText')
        user_id = data.get('userId')

        if not script_text or not user_id:
            return jsonify({"error": "Invalid payload. 'scriptText' and 'userId' are required."}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO Scripts (Company_ID, ScriptText, LastModifiedBy, Timestamp)
            VALUES (?, ?, ?, ?);
        """
        cursor.execute(query, (company_id, script_text, user_id, datetime.now()))
        conn.commit()
        conn.close()

        return jsonify({"message": "Script saved successfully."}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500