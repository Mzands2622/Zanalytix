import pyodbc
import json
from flask import Blueprint, jsonify, request
from db import get_db_connection

admin_console_bp = Blueprint('admin_console', __name__)

@admin_console_bp.route('/api/add-company', methods=['POST'])
def add_company():
    conn = None
    cursor = None
    try:
        print("Adding company - start")
        data = request.json
        print(f"Received data: {data}")
        
        if not data:
            print("No data received in request")
            return jsonify({'status': 'error', 'message': 'No data received'}), 400
        
        company_name = data.get('companyName')
        headquarters_local_time = data.get('headquartersLocalTime')
        print(f"Company Name: {company_name}")
        print(f"Headquarters Local Time: {headquarters_local_time}")

        # Only validate that company_name is not empty
        if not company_name:
            print(f"Missing company name")
            return jsonify({'status': 'error', 'message': 'Company name is required'}), 400

        # Convert empty string to None for headquarters_local_time
        if headquarters_local_time == '':
            headquarters_local_time = None

        print("Connecting to database")
        conn = get_db_connection()
        cursor = conn.cursor()

        print("Executing insert query")
        cursor.execute("""
            INSERT INTO Profile_Table (Company_Name, Headquarters_Local_Time)
            VALUES (?, ?)
        """, (company_name, headquarters_local_time))

        print("Committing transaction")
        conn.commit()
        
        print("Company added successfully")
        return jsonify({'status': 'success', 'message': 'Company added successfully'}), 201

    except pyodbc.Error as e:
        print(f"Database error occurred: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    except Exception as e:
        print(f"Unexpected error occurred: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Unexpected error: {str(e)}'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")

@admin_console_bp.route('/api/get-programmers', methods=['GET'])
def get_programmers():
    conn = None
    cursor = None
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # Query to select programmers and their associated companies
        cursor.execute("""
            SELECT Programmer_ID, UserID, Companies
            FROM Programmers
        """)
        results = cursor.fetchall()

        programmers = [
            {
                'userId': row[1],  # UserID
                'programmerId': row[0],  # Programmer_ID
                'companyList': eval(row[2]) if row[2] else []  # Companies
            } for row in results
        ]

        # Fetch first and last names from ProgrammerContacts
        for programmer in programmers:
            cursor.execute("""
                SELECT FirstName, LastName
                FROM ProgrammerContacts
                WHERE UserID = ?
            """, programmer['userId'])
            name_result = cursor.fetchone()
            if name_result:
                programmer['firstName'] = name_result[0]
                programmer['lastName'] = name_result[1]
            else:
                programmer['firstName'] = ''
                programmer['lastName'] = ''

        return jsonify(programmers), 200

    except pyodbc.Error as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@admin_console_bp.route('/api/update-programmer-companies/<int:user_id>', methods=['POST'])
def update_programmer_companies(user_id):
    conn = None
    cursor = None
    try:
        data = request.json
        if not data or 'companyList' not in data:
            return jsonify({'status': 'error', 'message': 'No data received or missing company list'}), 400

        company_list = data['companyList']
        
        conn = get_db_connection()
        cursor = conn.cursor()

        # Update the Programmer's company list in the Programmers_Table
        cursor.execute("""
            UPDATE Programmers
            SET Companies = ?
            WHERE UserID = ?
        """, (json.dumps(company_list), user_id))

        conn.commit()
        return jsonify({'status': 'success', 'message': 'Companies updated successfully'}), 200

    except pyodbc.Error as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
